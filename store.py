"""Storage backends. The game only ever calls get(key) and put(key, doc, new).

ShadeStore - the real thing: every room is one record in your shadeDB partition,
             reached with plain HTTPS POSTs (standard library only).
FileStore  - offline mode: a local JSON file, so the game runs with no network
             and no account. Also the default until you add credentials.
"""
import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.parse
from pathlib import Path


class FileStore:
    name = "local file"
    online = False

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.docs = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, key):
        with self.lock:
            doc = self.docs.get(key)
            return json.loads(json.dumps(doc)) if doc else None

    def _flush(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.docs))
        tmp.replace(self.path)

    def put(self, key, doc, new=False):
        with self.lock:
            self.docs[key] = json.loads(json.dumps(doc))
            self._flush()

    def delete(self, key):
        with self.lock:
            if self.docs.pop(key, None) is not None:
                self._flush()


class ShadeError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code} {detail}".strip())
        self.code, self.detail = code, detail


class ShadeClient:
    """Minimal shadeDB HTTP client.

    Each thread keeps one HTTPS connection open and reuses it, so a query costs one
    network round trip instead of a fresh TCP + TLS handshake every time. That alone
    removes several round trips per request, which matters most on a slow link.
    Retries ERR_TRY_AGAIN, HTTP 429 and (for reads and updates) dropped connections.
    """

    def __init__(self, endpoint, dbid, cluster_token, connection_token, timeout=10):
        self.endpoint, self.dbid, self.timeout = endpoint, dbid, timeout
        self.cluster_token, self.connection_token = cluster_token, connection_token
        self.u = urllib.parse.urlsplit(endpoint)
        self.local = threading.local()

    @property
    def host(self):
        return self.u.hostname

    @property
    def port(self):
        return self.u.port or (443 if self.u.scheme == "https" else 80)

    def _new_conn(self):
        cls = http.client.HTTPSConnection if self.u.scheme == "https" else http.client.HTTPConnection
        return cls(self.u.hostname, self.u.port, timeout=self.timeout)

    def _post(self, snl, fresh=False):
        body = json.dumps({"token": self.cluster_token, "cntoken": self.connection_token,
                           "dbid": self.dbid, "SNL": snl}).encode()
        path = (self.u.path or "/") + (("?" + self.u.query) if self.u.query else "")
        for attempt in (0, 1):
            old = None if fresh else getattr(self.local, "conn", None)
            conn = old or self._new_conn()
            try:
                conn.request("POST", path, body, {"Content-Type": "application/json"})
                res = conn.getresponse()
                raw = res.read()
            except (http.client.HTTPException, OSError) as exc:
                conn.close()
                self.local.conn = None
                if old is not None and attempt == 0 and isinstance(
                        exc, (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError,
                              http.client.BadStatusLine, http.client.CannotSendRequest)):
                    continue  # the server closed an idle connection before seeing the request
                raise ShadeError("HTTP_UNREACHABLE", str(exc)) from None
            if fresh or res.will_close:
                conn.close()
                if not fresh:
                    self.local.conn = None
            else:
                self.local.conn = conn
            if res.status >= 400:
                raise ShadeError(f"HTTP_{res.status}", res.getheader("Retry-After") or "")
            try:
                return json.loads(raw)
            except ValueError:
                raise ShadeError("HTTP_BAD_RESPONSE", raw[:80].decode("utf-8", "replace")) from None

    def tcp_rtt(self, n=5):
        """Milliseconds to open a bare TCP connection to the database host: the network round trip."""
        ip = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)[0][4][0]  # DNS is not timed
        out = []
        for _ in range(n):
            t = time.perf_counter()
            s = socket.create_connection((ip, self.port), timeout=5)
            out.append((time.perf_counter() - t) * 1000)
            s.close()
        return out

    def query(self, snl, retry_network=True, fresh=False):
        for attempt in range(5):
            try:
                data = self._post(snl, fresh=fresh)
            except ShadeError as exc:
                if exc.code == "HTTP_429" and attempt < 2:
                    time.sleep(min(float(exc.detail or 1), 3))
                    continue
                if exc.code == "HTTP_UNREACHABLE" and retry_network and attempt < 2:
                    time.sleep(0.4 * (attempt + 1))  # a dropped connection on a phone, say
                    continue
                raise
            if not (isinstance(data, dict) and data.get("status") == "failed"):
                return data.get("message") if isinstance(data, dict) else data
            code, _, detail = str(data.get("message", "query failed")).partition(";")
            if code.strip() == "ERR_TRY_AGAIN" and attempt < 4:
                time.sleep(0.1 * 2 ** attempt)
                continue
            raise ShadeError(code.strip(), detail.strip())


def _esc(value):
    return re.sub(r"([:;&|/\\])", r"\\\1", value)


# Errors that mean "fix your setup", never "record not found".
_HARD = {"ERR_PARTITION_NOT_EXIST", "ERR_SNL_SYNTAX_MALFORMED", "ERR_MAINTENANCE_ACTIVE",
         "ERR_INGESTION_PAUSED"}


class ShadeStore:
    """One room = one record in the partition: {"room": key, "data": "<room JSON>"}.

    The whole room document rides in `data`, so game rules can change without
    schema changes. Credentials stay in this server process, never in the browser.

    Reads are defensive. This server is the only writer, so it remembers the newest
    version of every room it has written (`latest`). If shadeDB ever answers with an
    older copy (duplicate records for one room, or a lagging read), the newer version
    wins and is written back (it only ever fires if the database answers with something
    older than what this server just wrote, and it logs when it does). Caching proper is
    shadeDB's job, so there is no app-side cache unless HD_CACHE_TTL is set above 0, which
    lets many
    polling clients share one database read.
    """
    name = "shadeDB"
    online = True

    def __init__(self):
        endpoint = os.environ["SHADEDB_ENDPOINT"]
        self.partition = os.environ.get("SHADEDB_PARTITION", "duelers")
        self.ttl = float(os.environ.get("HD_CACHE_TTL", "0"))
        self.cache, self.latest, self.warned, self.healed = {}, {}, set(), {}
        self.client = ShadeClient(
            endpoint,
            os.environ.get("SHADEDB_DBID") or endpoint.rstrip("/").rsplit("/", 1)[-1],
            os.environ["SHADEDB_CLUSTER_TOKEN"],
            os.environ["SHADEDB_CONNECTION_TOKEN"],
            timeout=float(os.environ.get("SHADEDB_TIMEOUT", "10")),
        )

    def _head(self):
        return f"partition #{self.partition}#;\n"

    @staticmethod
    def _age(doc):
        """Orders versions of one room: later save first, then higher revision."""
        return (doc.get("updated", 0), doc.get("rev", 0)) if isinstance(doc, dict) else (0, 0)

    def _update_stmt(self, key, raw):
        return f"{self._head()}UPDATE;\nstr<room>::str<{_esc(key)}>;\n{json.dumps({'data': raw})};"

    def get(self, key):
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return json.loads(hit[1])
        try:
            rows = self.client.query(f"{self._head()}FETCH;\nstr<room>::str<{_esc(key)}>;")
        except ShadeError as exc:
            if exc.code.startswith("HTTP_") or exc.code in _HARD:
                raise
            print(f"[shadeDB] fetch {key}: {exc}")
            rows = None
        if isinstance(rows, dict):
            rows = [rows]
        found = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("room") == key and "data" in row:
                try:
                    found.append((self._age(json.loads(row["data"])), row["data"]))
                except ValueError:
                    pass
        if len(found) > 1 and key not in self.warned:
            self.warned.add(key)
            print(f"[shadeDB] WARNING: {len(found)} records share room={key}. Mark `room` as a unique "
                  f"field in partition '{self.partition}' (see README). Using the newest copy.")
        best = max(found, key=lambda f: f[0]) if found else None
        mine = self.latest.get(key)
        if mine and (best is None or best[0] < mine[0]):
            print(f"[shadeDB] stale read for {key}: using the newer copy this server wrote")
            best = mine
            if time.time() - self.healed.get(key, 0) > 5:  # converge the database on our copy
                self.healed[key] = time.time()
                try:
                    self.client.query(self._update_stmt(key, mine[1]))
                except ShadeError as exc:
                    print(f"[shadeDB] heal {key}: {exc}")
        if best is None:
            self.cache.pop(key, None)
            return None
        self.cache[key] = (time.time(), best[1])
        return json.loads(best[1])

    def put(self, key, doc, new=False):
        raw = json.dumps(doc, separators=(",", ":"))
        try:
            if new:  # an insert is never repeated blindly
                self.client.query(f"{self._head()}INSERT;\n{json.dumps({'room': key, 'data': raw})};",
                                  retry_network=False, fresh=True)
            else:
                self.client.query(self._update_stmt(key, raw))
        except ShadeError as exc:
            if exc.code != "ERR_NO_CHANGES_MADE":
                raise
        self.cache[key] = (time.time(), raw)
        self.latest[key] = (self._age(doc), raw)
        if len(self.latest) > 500:  # keep memory bounded: drop the oldest rooms
            for k, _ in sorted(self.latest.items(), key=lambda kv: kv[1][0])[:100]:
                self.latest.pop(k, None)

    def delete(self, key):
        """Remove the room. If duplicates exist (room not unique), keep deleting until none are left."""
        for _ in range(5):
            try:
                self.client.query(f"{self._head()}DELETE;\nstr<room>::str<{_esc(key)}>;")
            except ShadeError as exc:
                if exc.code.startswith("HTTP_") or exc.code in _HARD:
                    raise
                break  # nothing (more) to delete
            try:
                rows = self.client.query(f"{self._head()}FETCH;\nstr<room>::str<{_esc(key)}>;")
            except ShadeError:
                break
            if not (isinstance(rows, list) and any(isinstance(r, dict) and r.get("room") == key for r in rows)):
                break
        self.cache.pop(key, None)
        self.latest.pop(key, None)


def make_store(base_dir):
    needed = ("SHADEDB_ENDPOINT", "SHADEDB_CONNECTION_TOKEN", "SHADEDB_CLUSTER_TOKEN")
    offline = os.environ.get("HD_MODE", "").lower() == "offline"
    if not offline and all(os.environ.get(k) for k in needed):
        return ShadeStore()
    return FileStore(Path(base_dir) / ".local-db.json")
