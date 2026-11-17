"""A tiny in-memory stand-in for the shadeDB HTTP endpoint, for tests only.

It understands just the statements Heaven Duels sends (partition, INSERT, FETCH,
UPDATE, OVERWRITE, DELETE) as documented at https://shadedb.duckdns.org/llms.
It checks request shape and tokens, nothing more: it is not the real engine.

Options let tests misbehave on purpose:
  unique=False       the `room` field is not a unique key, so INSERT can duplicate it
  stale_fetch=True   FETCH keeps answering with the first copy ever inserted
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKENS = dict(token="cluster-x", cntoken="conn-x", dbid="db-x")


class Fake:
    def __init__(self, partitions=("duelers",), unique=True, stale_fetch=False):
        self.data = {p: [] for p in partitions}
        self.snap = {}
        self.unique, self.stale_fetch = unique, stale_fetch
        self.queries = []
        self.try_again_once = False
        self.connections = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # keep-alive, like the real endpoint

            def setup(self):
                super().setup()
                fake.connections += 1

            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if any(req.get(k) != v for k, v in TOKENS.items()):
                    self.send_response(403); self.send_header("Content-Length", "0"); self.end_headers(); return
                raw = json.dumps(fake.run(req["SNL"])).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/connect/db-x"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()

    def run(self, snl):
        self.queries.append(snl)
        if self.try_again_once:
            self.try_again_once = False
            return {"status": "failed", "message": "ERR_TRY_AGAIN"}
        m = re.match(r"(?:partition #(.+?)#;\s*)?(INSERT|OVERWRITE|UPDATE|FETCH|DELETE);\s*(.*)", snl, re.S)
        if not m:
            return {"status": "failed", "message": "ERR_SNL_SYNTAX_MALFORMED"}
        part, mode, rest = m.groups()
        part = part or "duelers"
        if part not in self.data:
            return {"status": "failed", "message": "ERR_PARTITION_NOT_EXIST"}
        table = self.data[part]
        if mode == "INSERT":
            rec = json.loads(rest.strip().rstrip(";"))
            if self.unique and any(r["room"] == rec["room"] for r in table):
                return {"status": "failed", "message": "ERR_STORAGE_CONSTRAINT_VIOLATION ; room `%s`" % rec["room"]}
            table.append(rec)
            self.snap.setdefault(rec["room"], dict(rec))
            return {"status": "success", "message": "inserted"}
        pair = re.match(r"str<room>::str<(.+?)>;\s*(.*)", rest, re.S)
        key = pair.group(1).replace("\\", "")
        matches = [r for r in table if r["room"] == key]
        if mode == "FETCH":
            if self.stale_fetch:
                return {"status": "success", "message": [self.snap[key]] if key in self.snap else []}
            return {"status": "success", "message": [dict(r) for r in matches]}
        if not matches:
            return {"status": "failed", "message": "ERR_NO_RECORD"}
        if mode == "DELETE":
            table.remove(matches[0])
            return {"status": "success", "message": "deleted"}
        body = json.loads(pair.group(2).strip().rstrip(";"))
        if mode == "OVERWRITE":
            if matches[0] == body:
                return {"status": "failed", "message": "ERR_NO_CHANGES_MADE"}
            matches[0].clear(); matches[0].update(body)
            return {"status": "success", "message": "overwritten"}
        changed = False  # UPDATE merges the supplied fields into every matching record
        for r in matches:
            for k, v in body.items():
                if r.get(k) != v:
                    r[k], changed = v, True
        if not changed:
            return {"status": "failed", "message": "ERR_NO_CHANGES_MADE"}
        return {"status": "success", "message": [dict(r) for r in matches]}
