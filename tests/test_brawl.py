"""Heaven Brawl: the room side, and the live sync that rides on shadeDB."""
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
import realtime  # noqa: E402
from fake_shadedb import Fake  # noqa: E402
from store import FileStore, ShadeStore  # noqa: E402


class Brawl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        A.store = FileStore(Path(self.tmp.name) / "db.json")
        self.c = A.app.test_client()
        realtime._auth.clear(); realtime._created.clear(); realtime._lastn.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, path, **body):
        return self.c.post(path, json=body)

    def match(self, name="Dojo"):
        a = self.post("/api/create", game="brawl", room=name, name="Ash").json
        b = self.post("/api/join", room=name, name="Bo").json
        return a, b

    def pick(self, who, cls):
        return self.post("/api/move", key=who["key"], token=who["token"], move={"pick": cls})

    def started(self):
        a, b = self.match()
        self.pick(a, "seraph")
        v = self.pick(b, "cherub").json["state"]
        return a, b, v["gen"]

    def sync(self, who, gen, rec=None, key=None):
        return self.post("/api/brawl/sync", key=key or who["key"], token=who["token"], gen=gen, rec=rec)

    def view(self, who):
        return self.c.get(f"/api/room/{who['key']}?token={who['token']}").json

    def test_picks_are_secret_then_revealed(self):
        a, b = self.match()
        v = self.pick(a, "seraph").json["state"]
        self.assertEqual((v["phase"], v["me"], v["opp"]), ("pick", None, None))
        self.assertNotIn("seraph", json.dumps(self.view(b)["state"]))
        v = self.pick(b, "cherub").json["state"]
        self.assertEqual((v["phase"], v["me"], v["opp"]), ("fight", "cherub", "seraph"))
        self.assertEqual(self.pick(a, "paladin").status_code, 400)

    def test_sync_needs_a_running_match_and_the_right_credentials(self):
        a, b = self.match()
        self.assertEqual(self.sync(a, 1).status_code, 409)  # nobody has picked yet
        self.pick(a, "seraph"); gen = self.pick(b, "cherub").json["state"]["gen"]
        self.assertEqual(self.sync(a, gen).status_code, 200)
        self.assertEqual(self.sync(a, gen + 1).status_code, 409)
        self.assertEqual(self.post("/api/brawl/sync", key=a["key"], token="nope", gen=gen).status_code, 403)
        self.assertEqual(self.post("/api/brawl/sync", key="hd_missing", token="x", gen=gen).status_code, 404)

    def test_each_player_writes_their_own_record_and_reads_the_others(self):
        a, b, gen = self.started()
        self.assertIsNone(self.sync(a, gen, rec=dict(g=gen, n=1, s=dict(x=250, hp=100))).json["opp"])
        got = self.sync(b, gen, rec=dict(g=gen, n=1, s=dict(x=550, hp=95))).json
        self.assertEqual((got["slot"], got["opp"]["s"]["x"]), ("p2", 250))
        again = self.sync(a, gen).json  # a read-only call (no rec) still returns the opponent
        self.assertEqual(again["opp"]["s"]["hp"], 95)
        keys = sorted(k for k in A.store.docs if k.startswith("bs_"))
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[0].endswith("_p1") and keys[1].endswith("_p2"))
        self.assertIn("db", got)

    def test_a_late_older_update_never_overwrites_a_newer_one(self):
        a, b, gen = self.started()
        self.sync(a, gen, rec=dict(g=gen, n=5, s=dict(x=300)))
        self.sync(a, gen, rec=dict(g=gen, n=4, s=dict(x=111)))  # arrives late
        self.assertEqual(self.sync(b, gen).json["opp"]["s"]["x"], 300)

    def test_oversized_updates_are_refused(self):
        a, b, gen = self.started()
        self.assertEqual(self.sync(a, gen, rec=dict(g=gen, n=1, junk="x" * 5000)).status_code, 413)

    def test_only_the_host_can_report_the_result_and_streams_are_cleaned_up(self):
        a, b, gen = self.started()
        self.sync(a, gen, rec=dict(g=gen, n=1, s={})); self.sync(b, gen, rec=dict(g=gen, n=1, s={}))
        fin = dict(finish=dict(winner="p2", wins=dict(p1=1, p2=2)))
        self.assertEqual(self.post("/api/move", key=b["key"], token=b["token"], move=fin).status_code, 400)
        self.assertEqual(self.post("/api/move", key=a["key"], token=a["token"], move=dict(finish=dict(winner="x"))).status_code, 400)
        v = self.post("/api/move", key=a["key"], token=a["token"], move=fin).json
        self.assertEqual((v["status"], v["winner"], v["result"]), ("done", "p2", "Best of three, 1 to 2"))
        self.assertFalse([k for k in A.store.docs if k.startswith("bs_")])
        self.assertEqual(self.sync(a, gen).status_code, 409)  # the match is over

    def test_rematch_starts_a_fresh_match_and_leaving_deletes_the_room_and_streams(self):
        a, b, gen = self.started()
        self.sync(a, gen, rec=dict(g=gen, n=1, s={}))
        self.post("/api/resign", key=b["key"], token=b["token"])
        for who in (a, b):
            v = self.post("/api/rematch", key=who["key"], token=who["token"]).json
        self.assertEqual(v["state"]["phase"], "pick")
        self.assertNotEqual(v["state"]["gen"], gen)
        self.assertFalse([k for k in A.store.docs if k.startswith("bs_")])
        self.pick(a, "paladin"); gen2 = self.pick(b, "valkyrie").json["state"]["gen"]
        self.sync(a, gen2, rec=dict(g=gen2, n=1, s={}))
        self.assertTrue(self.post("/api/leave", key=a["key"], token=a["token"]).json["deleted"])
        self.assertFalse([k for k in A.store.docs if k.startswith("bs_")])

    def test_practice_against_the_computer_needs_no_server_moves(self):
        a = self.post("/api/create", game="brawl", name="Solo", bot=True).json
        v = self.pick(a, "valkyrie").json
        self.assertEqual((v["state"]["phase"], v["status"]), ("fight", "active"))
        self.assertEqual(v["state"]["opp"] is not None, True)  # the computer already picked a fighter

    def test_over_shadedb_with_two_separate_records(self):
        fake = Fake()
        os.environ.update(SHADEDB_ENDPOINT=fake.url, SHADEDB_DBID="db-x", SHADEDB_CLUSTER_TOKEN="cluster-x",
                          SHADEDB_CONNECTION_TOKEN="conn-x", SHADEDB_PARTITION="duelers")
        try:
            A.store = ShadeStore()
            a, b, gen = self.started()
            for n in range(1, 6):  # fast, repeated updates from both players
                self.sync(a, gen, rec=dict(g=gen, n=n, s=dict(x=n)))
                got = self.sync(b, gen, rec=dict(g=gen, n=n, s=dict(x=100 + n))).json
            self.assertEqual(got["opp"]["s"]["x"], 5)
            self.assertEqual(self.sync(a, gen).json["opp"]["s"]["x"], 105)
            recs = [r for r in fake.data["duelers"] if r["room"].startswith("bs_")]
            self.assertEqual(sorted(r["room"][-2:] for r in recs), ["p1", "p2"])  # no duplicates piling up
            realtime._created.clear()  # as if the server restarted: updates must still work
            self.assertEqual(self.sync(a, gen, rec=dict(g=gen, n=99, s=dict(x=7))).status_code, 200)
            self.assertEqual(self.sync(b, gen).json["opp"]["s"]["x"], 7)
        finally:
            fake.stop()


if __name__ == "__main__":
    unittest.main()
