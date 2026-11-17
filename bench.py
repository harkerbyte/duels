"""Speed test: is lag coming from shadeDB, or from the network?

The server times a batch of real queries against your database and reports three things
separately: the bare network round trip to the database host, how long reads and writes
take, and what that adds up to. The browser adds its own measurement of the hop to this
server. verdict() turns the numbers into a plain-language call."""
import json
import statistics
import threading
import time

from flask import Response, jsonify, request

from store import ShadeError, ShadeStore

_run_lock = threading.Lock()
_state = {"last": 0.0}
SCRATCH = "hd_bench"


def stats(xs):
    if not xs:
        return None
    s = sorted(xs)
    return dict(n=len(s), min=round(s[0], 1), avg=round(sum(s) / len(s), 1), median=round(statistics.median(s), 1),
                p95=round(s[min(len(s) - 1, round(0.95 * (len(s) - 1)))], 1), max=round(s[-1], 1))


def verdict(res, client_ping=None):
    """Where does the time go? Plain words, with the numbers that back them up."""
    if not res.get("online"):
        return dict(level="info", headline="Offline mode: there is no database trip to measure.",
                    points=["Add shadeDB credentials to .env (and leave out --offline) to benchmark the real thing."])
    if not res.get("read") or not res.get("write"):
        return dict(level="warn", headline="Some queries failed, so the numbers are incomplete.",
                    points=[f"The database said: {e}" for e in res.get("errors", [])[:3]])
    rtt, read, write = res["tcp"]["min"], res["read"]["median"], res["write"]["median"]
    work = max(0.0, read - rtt)
    points = [f"Network round trip from this server to shadeDB: {rtt:.0f} ms.",
              f"A read takes {read:.0f} ms and a write {write:.0f} ms. Of a read, about {rtt:.0f} ms is the trip "
              f"and about {work:.0f} ms is shadeDB working."]
    cold = res.get("cold")
    if cold and cold - read >= 100:
        points.append(f"A brand new connection costs {cold - read:.0f} ms more than a reused one. "
                      "The game server reuses its connection, so you only pay that once.")
    if read <= 150 and write <= 250:
        level, head = "good", "Fast. Neither the network nor shadeDB is slowing you down."
        points.append("If the game still feels laggy, look at the link between your device and this game server.")
    elif rtt >= 0.55 * read:
        level, head = "network", "The network is the bottleneck, not shadeDB."
        points.append("Most of each query is time on the wire. A closer or faster connection helps more than "
                      "anything on the database side.")
    else:
        level, head = "database", "shadeDB is taking longer than the network accounts for."
        points.append(f"Roughly {work:.0f} ms per read is spent inside the database or its front door. "
                      "Run the test a few times: if it stays high, that is worth reporting to shadeDB.")
    if client_ping is not None and client_ping >= 150:
        points.append(f"Your device is also slow to reach this game server ({client_ping:.0f} ms).")
    return dict(level=level, headline=head, points=points)


def register(app, get_store, fail, now):
    @app.get("/api/ping")
    def ping():
        resp = jsonify(t=time.time())
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/api/bench/blob")
    def blob():
        kb = max(1, min(512, int(request.args.get("kb", 256) or 256)))
        return Response(b"\0" * (kb * 1024), mimetype="application/octet-stream",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/bench/run")
    def run():
        d = request.get_json(silent=True) or {}
        n = max(3, min(25, int(d.get("n", 10) or 10)))
        try:
            client_ping = float(d["client_ping"]) if d.get("client_ping") is not None else None
        except (TypeError, ValueError):
            client_ping = None
        if time.time() - _state["last"] < 2 or not _run_lock.acquire(blocking=False):
            return fail("A benchmark just ran. Give it a couple of seconds.", 429)
        try:
            store = get_store()
            res = dict(online=bool(store.online), backend=store.name, n=n)
            ms = lambda t: (time.perf_counter() - t) * 1000  # noqa: E731
            if not isinstance(store, ShadeStore):  # offline mode: time the local file store
                reads, writes = [], []
                store.put(SCRATCH, {"bench": True, "n": 0})
                for i in range(n):
                    t = time.perf_counter(); store.get(SCRATCH); reads.append(ms(t))
                    t = time.perf_counter(); store.put(SCRATCH, {"bench": True, "n": i}); writes.append(ms(t))
                store.delete(SCRATCH)
                res.update(read=stats(reads), write=stats(writes), reads=[round(x, 1) for x in reads],
                           writes=[round(x, 1) for x in writes])
            else:
                c, errors = store.client, []
                sel = f"{store._head()}FETCH;\nstr<room>::str<{SCRATCH}>;"
                if store.get(SCRATCH) is None:  # a scratch record the test reads and updates
                    store.put(SCRATCH, {"bench": True, "n": 0, "updated": now()}, new=True)
                res.update(host=c.host, partition=store.partition)
                try:
                    res["tcp"] = stats(c.tcp_rtt(5))
                except OSError as exc:
                    errors.append(f"TCP connect failed: {exc}")
                t = time.perf_counter()
                try:
                    c.query(sel, fresh=True)
                    res["cold"] = round(ms(t), 1)
                    c.query(sel)  # open the reusable connection; not timed
                except ShadeError as exc:
                    errors.append(str(exc))
                reads, writes = [], []
                for i in range(n):
                    t = time.perf_counter()
                    try:
                        c.query(sel)
                        reads.append(ms(t))
                    except ShadeError as exc:
                        errors.append(str(exc))
                for i in range(n):
                    stmt = store._update_stmt(SCRATCH, json.dumps({"bench": True, "n": i, "t": time.time()}))
                    t = time.perf_counter()
                    try:
                        c.query(stmt)
                        writes.append(ms(t))
                    except ShadeError as exc:
                        if exc.code == "ERR_NO_CHANGES_MADE":
                            writes.append(ms(t))  # still a full round trip
                        else:
                            errors.append(str(exc))
                res.update(read=stats(reads), write=stats(writes), reads=[round(x, 1) for x in reads],
                           writes=[round(x, 1) for x in writes], errors=errors[:5])
            res["verdict"] = verdict(res, client_ping)
            return jsonify(res)
        finally:
            _state["last"] = time.time()
            _run_lock.release()
