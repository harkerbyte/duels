import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["HD_MODE"] = "offline"

import app as A  # noqa: E402
from fake_shadedb import Fake  # noqa: E402
from games import chess, snakes  # noqa: E402
from store import FileStore, ShadeError, ShadeStore  # noqa: E402


def perft(pos, d):
    return 1 if d == 0 else sum(perft(chess.make(pos, m), d - 1) for m in chess.legal(pos))


class ChessEngine(unittest.TestCase):
    def test_perft_known_positions(self):
        cases = [("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", [20, 400, 8902]),
                 ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039]),
                 ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812]),
                 ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264]),
                 ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486])]
        for fen, expected in cases:
            pos = chess.parse(fen)
            self.assertEqual([perft(pos, i + 1) for i in range(len(expected))], expected, fen)

    def test_fen_roundtrip(self):
        fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
        self.assertEqual(chess.to_fen(chess.parse(fen)), fen)

    def test_stalemate_and_insufficient(self):
        self.assertEqual(chess.outcome(chess.parse("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), 1), "Stalemate")
        self.assertEqual(chess.outcome(chess.parse("8/8/4k3/8/8/3K4/8/6N1 w - - 0 1"), 1), "Insufficient material")


class ChessRooms(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        A.store = FileStore(Path(self.tmp.name) / "db.json")
        self.c = A.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def room(self, game="chess", name="Pearly Gates", pw="", jpw=None, **extra):
        a = self.c.post("/api/create", json=dict(game=game, room=name, password=pw, name="Ash", **extra)).json
        r = self.c.post("/api/join", json=dict(room=name, password=pw if jpw is None else jpw, name="Bo"))
        return a, r

    def mv(self, who, **move):
        return self.c.post("/api/move", json=dict(key=who["key"], token=who["token"], move=move))

    def get(self, who):
        return self.c.get(f"/api/room/{who['key']}?token={who['token']}").json

    def test_fools_mate(self):
        a, r = self.room()
        b = r.json
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.mv(b, **{"from": "e7", "to": "e5"}).status_code, 400)  # not black's turn
        self.assertEqual(self.mv(a, **{"from": "e2", "to": "e5"}).status_code, 400)  # illegal
        for who, f, t in ((a, "f2", "f3"), (b, "e7", "e5"), (a, "g2", "g4"), (b, "d8", "h4")):
            self.assertEqual(self.mv(who, **{"from": f, "to": t}).status_code, 200)
        v = self.get(a)
        self.assertEqual((v["status"], v["winner"], v["result"]), ("done", "p2", "Checkmate"))
        self.assertEqual(v["state"]["moves"][-1], "Qh4#")
        self.assertEqual(v["score"], {"p1": 0, "p2": 1})

    def test_legal_moves_only_for_the_player_to_move(self):
        a, r = self.room()
        self.assertEqual(len(self.get(a)["state"]["legal"]), 10)  # 8 pawns + 2 knights
        self.assertEqual(self.get(r.json)["state"]["legal"], {})

    def test_promotion_and_en_passant(self):
        a, r = self.room()
        room = A.store.get(a["key"])
        room["state"]["fen"] = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        A.store.put(a["key"], room)
        v = self.mv(a, **{"from": "a7", "to": "a8", "promo": "n"}).json
        self.assertIn("a8=N", v["state"]["moves"][-1])
        self.assertIn("N3k3" if False else "N", v["state"]["fen"].split()[0])
        self.assertEqual(chess.parse("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")["ep"], chess.sq_index("d6"))

    def test_resign_draw_and_rematch_swaps_colours(self):
        a, r = self.room()
        b = r.json
        self.c.post("/api/draw", json=dict(key=a["key"], token=a["token"]))
        v = self.c.post("/api/draw", json=dict(key=b["key"], token=b["token"])).json
        self.assertEqual((v["status"], v["winner"], v["result"]), ("done", "draw", "Draw by agreement"))
        for who in (a, b):
            v = self.c.post("/api/rematch", json=dict(key=who["key"], token=who["token"])).json
        self.assertEqual((v["status"], v["state"]["white"]), ("active", "p2"))
        v = self.c.post("/api/resign", json=dict(key=a["key"], token=a["token"])).json
        self.assertEqual((v["winner"], v["result"]), ("p2", "Resignation"))

    def test_practice_bot_white_and_black(self):
        a = self.c.post("/api/create", json=dict(game="chess", name="Solo", bot=True, color="white")).json
        t = time.time()
        v = self.mv(a, **{"from": "e2", "to": "e4"}).json
        self.assertEqual(len(v["state"]["moves"]), 2)  # our move and the bot's reply
        self.assertLess(time.time() - t, 5)
        self.assertTrue(v["my_turn"] and v["vs_bot"])
        b = self.c.post("/api/create", json=dict(game="chess", name="Solo2", bot=True, color="black")).json
        v = self.get(b)
        self.assertEqual(len(v["state"]["moves"]), 1)  # the bot (white) already opened
        self.assertEqual(self.c.post("/api/draw", json=dict(key=b["key"], token=b["token"])).status_code, 409)


class SnakesRooms(ChessRooms):
    def roll(self, who, value):
        with mock.patch("games.snakes.random.randint", return_value=value):
            return self.mv(who, action="roll")

    def test_roll_ladder_snake_exact_and_six(self):
        a, r = self.room(game="snakes")
        b = r.json
        self.assertEqual(self.roll(b, 3).status_code, 400)  # p1 starts
        v = self.roll(a, 3).json  # 0 -> 3
        self.assertEqual((v["state"]["pos"]["p1"], v["state"]["turn"]), (3, "p2"))
        v = self.roll(b, 4).json  # 0 -> 4, ladder to 14
        self.assertEqual(v["state"]["pos"]["p2"], 14)
        v = self.roll(a, 6).json  # 3 -> 9 -> ladder 31, and a six: p1 again
        self.assertEqual((v["state"]["pos"]["p1"], v["state"]["turn"]), (31, "p1"))
        room = A.store.get(a["key"])
        room["state"]["pos"]["p1"] = 14
        room["state"]["turn"] = "p1"
        A.store.put(a["key"], room)
        v = self.roll(a, 2).json  # 14 -> 16, serpent to 6
        self.assertEqual(v["state"]["pos"]["p1"], 6)

    def test_exact_finish_wins(self):
        a, r = self.room(game="snakes")
        room = A.store.get(a["key"])
        room["state"]["pos"]["p1"] = 98
        A.store.put(a["key"], room)
        # 98 is a serpent square only when landed on; 98 + 3 overshoots and is wasted
        v = self.roll(a, 3).json
        self.assertEqual(v["state"]["pos"]["p1"], 98)
        room = A.store.get(a["key"])
        room["state"]["turn"] = "p1"
        A.store.put(a["key"], room)
        v = self.roll(a, 2).json
        self.assertEqual((v["status"], v["winner"], v["state"]["pos"]["p1"]), ("done", "p1", 100))

    def test_board_is_consistent(self):
        ends = set(snakes.LADDERS.values()) | set(snakes.SNAKES.values())
        starts = set(snakes.LADDERS) | set(snakes.SNAKES)
        self.assertFalse(starts & set(snakes.SNAKES.values()) | (set(snakes.SNAKES) & set(snakes.LADDERS)))
        self.assertTrue(all(0 < s < 100 for s in snakes.SNAKES))
        self.assertTrue(all(snakes.SNAKES[s] < s for s in snakes.SNAKES))
        self.assertTrue(all(snakes.LADDERS[s] > s for s in snakes.LADDERS))
        self.assertTrue(ends)

    def test_practice_bot_plays_on_its_own(self):
        a = self.c.post("/api/create", json=dict(game="snakes", name="Solo", bot=True)).json
        for _ in range(400):
            v = self.get(a)
            if v["status"] == "done":
                break
            self.mv(a, action="roll")
        self.assertEqual(self.get(a)["status"], "done")

    # chess-only tests do not apply to this game
    test_fools_mate = test_legal_moves_only_for_the_player_to_move = test_promotion_and_en_passant = None
    test_resign_draw_and_rematch_swaps_colours = test_practice_bot_white_and_black = None


class Shared(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        A.store = FileStore(Path(self.tmp.name) / "db.json")
        self.c = A.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_room_and_names(self):
        a = self.c.post("/api/create", json=dict(game="chess", room="Pearly Gates", password="halo", name="Ash")).json
        bad = self.c.post("/api/join", json=dict(room="Pearly Gates", password="nope", name="Bo"))
        self.assertEqual(bad.status_code, 403)
        ok = self.c.post("/api/join", json=dict(room="pearly gates", password="halo", name="Bo"))
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn("halo", str(A.store.get(a["key"])))  # only a salted hash is stored
        full = self.c.post("/api/join", json=dict(room="Pearly Gates", password="halo", name="Cy"))
        self.assertEqual(full.status_code, 409)
        dup = self.c.post("/api/create", json=dict(game="snakes", room="PEARLY gates", name="X"))
        self.assertEqual(dup.status_code, 409)
        short = self.c.post("/api/create", json=dict(game="chess", room="a!", name="X"))
        self.assertEqual(short.status_code, 400)
        nogame = self.c.post("/api/create", json=dict(game="checkers", room="Valid Name", name="X"))
        self.assertEqual(nogame.status_code, 400)

    def test_build_id_lets_pages_refresh_themselves(self):
        meta = self.c.get("/api/meta").json
        a = self.c.post("/api/create", json=dict(game="chess", room="Build Room", name="Ash")).json
        v = self.c.get(f"/api/room/{a['key']}?token={a['token']}").json
        self.assertEqual(meta["build"], v["build"])

    def test_installable_app_files_are_served(self):
        man = self.c.get("/manifest.webmanifest")
        self.assertEqual(man.status_code, 200)
        data = man.get_json(force=True)
        self.assertIn(data["display"], ("fullscreen", "standalone"))
        for icon in data["icons"]:
            self.assertEqual(self.c.get(icon["src"]).status_code, 200)
        sw = self.c.get("/sw.js")
        self.assertEqual((sw.status_code, sw.headers["Service-Worker-Allowed"]), (200, "/"))
        self.assertIn("javascript", sw.mimetype)

    def test_unknown_page_is_404_not_500(self):
        self.assertEqual(self.c.get("/nope").status_code, 404)
        self.assertEqual(self.c.get("/api/nope").status_code, 404)
        self.assertEqual(self.c.get("/favicon.ico").status_code, 204)

    def test_reactions_and_chat_ids(self):
        a = self.c.post("/api/create", json=dict(game="chess", room="Reacts", name="Ash")).json
        b = self.c.post("/api/join", json=dict(room="Reacts", name="Bo")).json
        r = self.c.post("/api/emote", json=dict(key=a["key"], token=a["token"], emote="🔥")).json
        self.assertEqual([(x["s"], x["e"], x["n"]) for x in r["reactions"]], [("p1", "🔥", 1)])
        self.assertEqual(self.c.post("/api/emote", json=dict(key=a["key"], token=a["token"], emote="🔥")).status_code, 429)
        r = self.c.post("/api/emote", json=dict(key=b["key"], token=b["token"], emote="👏")).json
        self.assertEqual([x["n"] for x in r["reactions"]], [1, 2])
        self.assertEqual(self.c.post("/api/emote", json=dict(key=b["key"], token=b["token"], emote="x")).status_code, 403)
        for i, who in enumerate((a, b), 1):
            v = self.c.post("/api/chat", json=dict(key=who["key"], token=who["token"], text=f"hello {i}")).json
        self.assertEqual([m["i"] for m in v["chat"]], [1, 2])

    def test_manifest_and_icons_for_full_screen_install(self):
        m = self.c.get("/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.get_json(force=True)["display"], "fullscreen")
        for icon in m.get_json(force=True)["icons"]:
            self.assertEqual(self.c.get(icon["src"]).status_code, 200)

    def test_chat_and_claim(self):
        a = self.c.post("/api/create", json=dict(game="chess", room="Chatty", name="Ash")).json
        b = self.c.post("/api/join", json=dict(room="Chatty", name="Bo")).json
        ok = self.c.post("/api/chat", json=dict(key=a["key"], token=a["token"], text="<b>hi</b>"))
        self.assertEqual(ok.json["chat"][-1]["x"], "<b>hi</b>")  # stored raw, the client escapes
        spam = self.c.post("/api/chat", json=dict(key=a["key"], token=a["token"], text="again"))
        self.assertEqual(spam.status_code, 429)
        self.assertEqual(self.c.post("/api/chat", json=dict(key=a["key"], token="no", text="x")).status_code, 403)
        self.assertEqual(self.c.post("/api/claim", json=dict(key=a["key"], token=a["token"])).status_code, 409)
        room = A.store.get(a["key"])
        room["players"]["p2"]["seen"] = time.time() - 120
        A.store.put(a["key"], room)
        v = self.c.post("/api/claim", json=dict(key=a["key"], token=a["token"])).json
        self.assertEqual((v["winner"], v["result"]), ("p1", "Opponent left"))


class ShadeStoreTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        os.environ.update(SHADEDB_ENDPOINT=self.fake.url, SHADEDB_DBID="db-x",
                          SHADEDB_CLUSTER_TOKEN="cluster-x", SHADEDB_CONNECTION_TOKEN="conn-x",
                          SHADEDB_PARTITION="duelers", HD_CACHE_TTL="0")
        self.s = ShadeStore()

    def tearDown(self):
        self.fake.stop()

    def test_roundtrip_and_partition(self):
        doc = dict(name='Q "quoted"; tricky : / \\ ünï', n=[1, 2, 3])
        self.s.put("hd_room", doc, new=True)
        self.assertEqual(self.s.get("hd_room"), doc)
        self.assertTrue(self.fake.queries[0].startswith("partition #duelers#;\nINSERT;"))
        self.s.put("hd_room", {"x": 1})
        self.assertEqual(self.s.get("hd_room"), {"x": 1})
        self.assertIn("UPDATE;\nstr<room>::str<hd_room>;", self.fake.queries[-2])
        self.s.put("hd_room", {"x": 1})  # ERR_NO_CHANGES_MADE is a no-op
        self.assertIsNone(self.s.get("hd_missing"))

    def test_insert_collision_is_reported_not_overwritten(self):
        self.s.put("hd_r", {"v": 1}, new=True)
        with self.assertRaises(ShadeError) as cm:
            self.s.put("hd_r", {"v": 2}, new=True)
        self.assertEqual(cm.exception.code, "ERR_STORAGE_CONSTRAINT_VIOLATION")
        self.assertEqual(self.s.get("hd_r"), {"v": 1})

    def test_retry_on_try_again_and_bad_partition(self):
        self.fake.try_again_once = True
        self.s.put("hd_r", {"v": 1}, new=True)
        self.assertEqual(self.s.get("hd_r"), {"v": 1})
        self.s.partition = "nope"
        with self.assertRaises(ShadeError):
            self.s.get("hd_r")

    def test_network_blip_is_retried_for_reads_but_not_inserts(self):
        self.s.put("hd_r", {"v": 1}, new=True)
        real, calls = self.s.client._post, {"n": 0}

        def flaky(snl, fresh=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ShadeError("HTTP_UNREACHABLE", "blip")
            return real(snl)
        self.s.client._post = flaky
        self.assertEqual(self.s.get("hd_r"), {"v": 1})
        self.assertEqual(calls["n"], 2)
        calls["n"] = 0
        with self.assertRaises(ShadeError):  # an insert is never repeated blindly
            self.s.put("hd_new", {"v": 1}, new=True)
        self.assertEqual(calls["n"], 1)

    def test_duplicate_records_resolve_to_the_newest_copy(self):
        self.fake.unique = False  # `room` was never marked unique, so a duplicate can exist
        self.s.put("hd_r", {"updated": 10, "rev": 1, "who": "stale"}, new=True)
        self.s.put("hd_r", {"updated": 50, "rev": 4, "who": "fresh"}, new=True)
        restarted = ShadeStore()  # a new process knows nothing about what was written
        self.assertEqual(restarted.get("hd_r")["who"], "fresh")

    def test_stale_reads_cannot_undo_a_write(self):
        self.s.put("hd_r", {"updated": 10, "rev": 5, "v": "new"}, new=True)
        self.fake.data["duelers"][0].update(data=json.dumps({"updated": 10, "rev": 1, "v": "old"}))
        self.assertEqual(self.s.get("hd_r")["v"], "new")  # the database is behind: ours wins
        self.assertEqual(json.loads(self.fake.data["duelers"][0]["data"])["v"], "new")  # and it is healed

    def test_owner_sees_the_joiner_even_when_reads_are_stale(self):
        """The reported bug: the joiner's token worked once, then 403, and the owner never saw them."""
        self.fake.stale_fetch = True
        A.store = self.s
        c = A.app.test_client()
        a = c.post("/api/create", json=dict(game="chess", room="Quest", name="Owner")).json
        b = c.post("/api/join", json=dict(room="Quest", name="Guest")).json
        for _ in range(3):
            owner = c.get(f"/api/room/{a['key']}?token={a['token']}").json
            guest = c.get(f"/api/room/{b['key']}?token={b['token']}")
            self.assertEqual(guest.status_code, 200)
            self.assertEqual((owner["status"], owner["names"]["p2"]), ("active", "Guest"))
            time.sleep(0.01)
        third = c.post("/api/join", json=dict(room="Quest", name="Intruder"))
        self.assertEqual(third.status_code, 409)  # the room is really full

    def test_bad_token_is_403(self):
        self.s.client.connection_token = "wrong"
        with self.assertRaises(ShadeError) as cm:
            self.s.get("hd_r")
        self.assertEqual(cm.exception.code, "HTTP_403")

    def test_both_games_through_shadedb_store(self):
        A.store = self.s
        c = A.app.test_client()
        for game, move in (("chess", dict(**{"from": "e2"}, to="e4")), ("snakes", dict(action="roll"))):
            a = c.post("/api/create", json=dict(game=game, room=f"Cloud {game}", name="Ash")).json
            b = c.post("/api/join", json=dict(room=f"Cloud {game}", name="Bo")).json
            v = c.post("/api/move", json=dict(key=a["key"], token=a["token"], move=move)).json
            self.assertFalse(v["my_turn"] and game == "chess")
            seen = c.get(f"/api/room/{b['key']}?token={b['token']}").json
            self.assertEqual(seen["rev"], v["rev"])


if __name__ == "__main__":
    unittest.main()
