"""Leaving and deleting rooms, the fighting game, clans, the speed test, and connection reuse."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["HD_MODE"] = "offline"

import app as A  # noqa: E402
import bench  # noqa: E402
import clans  # noqa: E402
from fake_shadedb import Fake  # noqa: E402
from games import fight  # noqa: E402
from store import FileStore, ShadeStore  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        A.store = FileStore(Path(self.tmp.name) / "db.json")
        self.c = A.app.test_client()
        bench._state["last"] = 0

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, path, **body):
        return self.c.post(path, json=body)

    def room(self, game="chess", name="Pearly Gates", **extra):
        a = self.post("/api/create", game=game, room=name, name="Ash", **extra).json
        b = self.post("/api/join", room=name, name="Bo").json
        return a, b

    def poll(self, who):
        return self.c.get(f"/api/room/{who['key']}?token={who['token']}")


class LeavingRooms(Base):
    def test_host_leaving_deletes_the_room_by_default(self):
        a, b = self.room()
        r = self.post("/api/leave", key=a["key"], token=a["token"]).json
        self.assertTrue(r["deleted"])
        self.assertIsNone(A.store.get(a["key"]))
        gone = self.poll(b)
        self.assertEqual((gone.status_code, gone.json["error"]), (404, "This room was closed."))

    def test_host_can_keep_the_room_open(self):
        a, b = self.room(delete_on_leave=False)
        self.assertFalse(self.post("/api/leave", key=a["key"], token=a["token"]).json["deleted"])
        v = self.poll(b).json
        self.assertEqual((v["status"], v["winner"], v["result"]), ("done", "p2", "Host left"))
        self.assertTrue(self.post("/api/leave", key=b["key"], token=b["token"]).json["deleted"])  # last one out
        self.assertIsNone(A.store.get(a["key"]))

    def test_a_guest_leaving_frees_the_seat(self):
        a, b = self.room(delete_on_leave=False)
        self.assertFalse(self.post("/api/leave", key=b["key"], token=b["token"]).json["deleted"])
        v = self.poll(a).json
        self.assertEqual((v["status"], v["names"]["p2"]), ("waiting", ""))
        self.assertEqual(self.post("/api/join", room="Pearly Gates", name="Cy").status_code, 200)

    def test_practice_rooms_are_always_deleted_and_strangers_cannot_delete(self):
        solo = self.post("/api/create", game="chess", name="Solo", bot=True, delete_on_leave=False).json
        a, b = self.room(name="Other Room")
        self.post("/api/leave", key=a["key"], token="not-a-token")
        self.assertIsNotNone(A.store.get(a["key"]))
        self.assertTrue(self.post("/api/leave", key=solo["key"], token=solo["token"]).json["deleted"])
        self.assertIsNone(A.store.get(solo["key"]))


class FightingGame(Base):
    def move(self, who, **mv):
        return self.post("/api/move", key=who["key"], token=who["token"], move=mv)

    def started(self):
        a, b = self.room("fight")
        self.move(a, pick="seraph")
        self.assertEqual(self.move(a, pick="cherub").status_code, 400)  # one pick each
        self.move(b, pick="paladin")
        return a, b

    def test_picks_are_secret_until_both_have_chosen(self):
        a, b = self.room("fight")
        v = self.move(a, pick="seraph").json["state"]
        self.assertEqual((v["my_pick"], v["opp"]), ("seraph", None))
        theirs = self.poll(b).json["state"]
        self.assertTrue(theirs["opp_picked"])
        self.assertNotIn("seraph", json.dumps(theirs))
        v = self.move(b, pick="paladin").json["state"]
        self.assertEqual((v["phase"], v["me"]["cls"], v["opp"]["cls"]), ("fight", "paladin", "seraph"))

    def test_a_locked_move_is_hidden_and_rounds_resolve_together(self):
        a, b = self.started()
        self.assertEqual(self.move(a, move="strike").json["state"]["my_move"], "strike")
        theirs = self.poll(b).json
        self.assertTrue(theirs["state"]["opp_ready"])
        self.assertNotIn("strike", json.dumps(theirs["state"]))  # the pending move never leaves the server
        self.assertTrue(theirs["my_turn"])
        self.assertEqual(self.move(a, move="guard").status_code, 400)  # already locked in
        v = self.move(b, move="guard").json["state"]
        self.assertEqual((v["round"], v["my_move"]), (2, None))
        self.assertIn("chose", v["last"]["lines"][0])

    def test_costs_and_grace_are_enforced(self):
        a, b = self.started()
        self.assertEqual(self.move(a, move="judgment").status_code, 400)
        room = A.store.get(a["key"])
        room["state"]["fighters"]["p1"]["mp"] = 0
        A.store.put(a["key"], room)
        self.assertEqual(self.move(a, move="mend").status_code, 400)

    def test_rules(self):
        names = {"p1": "A", "p2": "B"}
        s = fight.new_state()
        for slot, cls in (("p1", "seraph"), ("p2", "paladin")):
            fight.apply(s, slot, {"pick": cls}, names)
        fight.apply(s, "p1", {"move": "ability"}, names)
        fight.apply(s, "p2", {"move": "strike"}, names)
        self.assertEqual((s["fighters"]["p2"]["burn"], s["fighters"]["p2"]["hp"]), (3, 100))  # smite + burning
        s["fighters"]["p1"]["grace"] = 5
        fight.apply(s, "p1", {"move": "judgment"}, names)
        fight.apply(s, "p2", {"move": "guard"}, names)
        self.assertEqual(s["fighters"]["p2"]["hp"], 100 - 3 - 40)  # judgment ignores guard

    def test_practice_against_the_computer_and_rematch(self):
        a = self.post("/api/create", game="fight", name="Solo", bot=True).json
        v = self.move(a, pick="valkyrie").json
        self.assertEqual(v["state"]["phase"], "fight")
        for _ in range(300):
            if v["status"] == "done":
                break
            mv = "judgment" if v["state"]["me"]["grace"] >= 5 else "strike"
            v = self.move(a, move=mv).json
        self.assertEqual(v["status"], "done")
        v = self.post("/api/rematch", key=a["key"], token=a["token"]).json
        self.assertEqual((v["status"], v["state"]["phase"]), ("active", "pick"))


class Clans(Base):
    def create(self, name="Night Owls", nick="Ash"):
        return self.post("/api/clan/create", name=name, nick=nick).json

    def view(self, m):
        return self.c.get(f"/api/clan/{m['id']}?token={m['token']}")

    def test_create_join_chat_and_leave(self):
        a = self.create()
        self.assertRegex(a["id"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        v = self.view(a).json
        self.assertEqual([m["n"] for m in v["members"]], ["Ash"])
        self.assertNotIn("token", json.dumps(v))
        self.assertNotIn(a["token"], json.dumps(v))  # tokens never leave the server
        b = self.post("/api/clan/join", id=a["id"].lower().replace("-", ""), nick="Bo").json  # lenient about format
        v = self.view(a).json
        self.assertEqual(sorted(m["n"] for m in v["members"]), ["Ash", "Bo"])
        self.assertEqual([h["e"] for h in v["history"]], ["created", "joined"])
        self.assertEqual(self.post("/api/clan/chat", id=a["id"], token=b["token"], text="hi all").status_code, 200)
        self.assertEqual(self.post("/api/clan/chat", id=a["id"], token=b["token"], text="again").status_code, 429)
        self.assertEqual(self.view(a).json["chat"][-1]["x"], "hi all")
        left = self.post("/api/clan/leave", id=a["id"], token=b["token"]).json
        self.assertFalse(left["deleted"])
        self.assertEqual([h["e"] for h in self.view(a).json["history"]][-1], "left")
        self.assertEqual(self.view(b).status_code, 403)

    def test_ownership_moves_on_and_empty_clans_disappear(self):
        a = self.create()
        b = self.post("/api/clan/join", id=a["id"], nick="Bo").json
        self.post("/api/clan/leave", id=a["id"], token=a["token"])
        v = self.view(b).json
        self.assertTrue(v["owner"])
        self.assertEqual(v["history"][-1]["e"], "owner")
        self.assertTrue(self.post("/api/clan/leave", id=a["id"], token=b["token"]).json["deleted"])
        self.assertEqual(self.view(b).status_code, 404)

    def test_permissions_and_limits(self):
        a = self.create()
        b = self.post("/api/clan/join", id=a["id"], nick="Bo").json
        self.assertEqual(self.post("/api/clan/disband", id=a["id"], token=b["token"]).status_code, 403)
        self.assertEqual(self.view({"id": a["id"], "token": "nope"}).status_code, 403)
        self.assertEqual(self.post("/api/clan/join", id="ZZZZ-ZZZZ", nick="X").status_code, 404)
        self.assertEqual(self.post("/api/clan/join", id="short", nick="X").status_code, 400)
        self.assertEqual(self.post("/api/clan/create", name="ab", nick="X").status_code, 400)
        clans.MAX_MEMBERS, old = 2, clans.MAX_MEMBERS
        try:
            self.assertEqual(self.post("/api/clan/join", id=a["id"], nick="Cy").status_code, 409)
        finally:
            clans.MAX_MEMBERS = old
        self.assertTrue(self.post("/api/clan/disband", id=a["id"], token=a["token"]).json["deleted"])
        self.assertEqual(self.view(a).status_code, 404)

    def test_game_invites_travel_through_the_clan_chat(self):
        a = self.create()
        ok = self.post("/api/clan/chat", id=a["id"], token=a["token"], text="",
                       invite=dict(room="Pearly Gates", game="chess")).json
        self.assertEqual(ok["chat"][-1]["inv"], dict(room="Pearly Gates", game="chess"))
        bad = self.post("/api/clan/chat", id=a["id"], token=a["token"], text="",
                        invite=dict(room="Pearly Gates", game="poker"))
        self.assertEqual(bad.status_code, 400)  # an invalid invite with no text has nothing to post


class DemoNotice(Base):
    def test_the_app_knows_when_it_is_on_the_demo_database(self):
        old = A.BASE
        try:
            A.BASE = Path(self.tmp.name)
            self.assertFalse(A.uses_demo_env())
            (A.BASE / ".env").write_text("# created by start.sh: shared demo database\nPORT=5000\n")
            self.assertTrue(A.uses_demo_env())
            self.assertFalse(self.c.get("/api/meta").json["demo"])  # offline storage is never "the demo database"
        finally:
            A.BASE = old


class SpeedTest(Base):
    def test_ping_and_blob(self):
        self.assertEqual(self.c.get("/api/ping").status_code, 200)
        self.assertEqual(len(self.c.get("/api/bench/blob?kb=4").data), 4096)

    def test_offline_run_and_cooldown(self):
        r = self.post("/api/bench/run", n=5, client_ping=3).json
        self.assertFalse(r["online"])
        self.assertEqual((r["read"]["n"], r["write"]["n"], r["verdict"]["level"]), (5, 5, "info"))
        self.assertEqual(self.post("/api/bench/run", n=5).status_code, 429)

    def test_verdicts(self):
        base = dict(online=True, errors=[])
        fast = dict(base, tcp=dict(min=20), read=dict(median=60), write=dict(median=90))
        self.assertEqual(bench.verdict(fast)["level"], "good")
        net = dict(base, tcp=dict(min=200), read=dict(median=260), write=dict(median=300))
        self.assertEqual(bench.verdict(net)["level"], "network")
        db = dict(base, tcp=dict(min=20), read=dict(median=400), write=dict(median=500))
        self.assertEqual(bench.verdict(db)["level"], "database")
        self.assertEqual(bench.verdict(dict(base, tcp=dict(min=5), read=None, write=None, errors=["ERR_X"]))["level"], "warn")
        slow_client = bench.verdict(fast, client_ping=400)
        self.assertTrue(any("slow to reach this game server" in p for p in slow_client["points"]))

    def test_run_against_shadedb_and_connection_reuse(self):
        fake = Fake()
        os.environ.update(SHADEDB_ENDPOINT=fake.url, SHADEDB_DBID="db-x", SHADEDB_CLUSTER_TOKEN="cluster-x",
                          SHADEDB_CONNECTION_TOKEN="conn-x", SHADEDB_PARTITION="duelers")
        try:
            A.store = ShadeStore()
            r = self.post("/api/bench/run", n=4, client_ping=12).json
            self.assertTrue(r["online"])
            self.assertEqual((r["read"]["n"], r["write"]["n"]), (4, 4))
            self.assertIn("min", r["tcp"])
            self.assertIn("cold", r)
            self.assertIn("verdict", r)
            before = fake.connections
            for _ in range(8):
                A.store.client.query(f"{A.store._head()}FETCH;\nstr<room>::str<hd_bench>;")
            self.assertEqual(fake.connections, before)  # eight queries, zero new connections
            A.store.client.local.conn.sock.close()  # the link dies under us: the next query recovers
            self.assertIsNotNone(A.store.get("hd_bench"))
        finally:
            fake.stop()


if __name__ == "__main__":
    unittest.main()
