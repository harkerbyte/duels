"""Real-time sync for Heaven Brawl. Still carried entirely by shadeDB.

Each player owns one small record (`bs_<room>_<match>_<slot>`) that holds their latest
fighter state and recent events. One call, POST /api/brawl/sync, writes your record and
reads your opponent's at the same time, so a round trip costs about one database
round trip. Nothing is pushed: each client simply asks again as soon as the last answer
arrives, as fast as the link allows. The server never interprets the game; it only
checks who you are and passes records along.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify, request

from store import ShadeError

POOL = ThreadPoolExecutor(max_workers=8)
MAX_REC = 3500  # bytes per update
_auth, _created, _lastn, _lock = {}, set(), {}, threading.Lock()


def stream_key(room_key, gen, slot):
    return f"bs_{room_key[3:] if room_key.startswith('hd_') else room_key}_{gen}_{slot}"


def drop(store, room):
    """Delete a match's stream records (best effort). Called when the match ends or the room goes."""
    st = room.get("state") or {}
    if room.get("game") != "brawl" or "gen" not in st:
        return
    for k in [k for k in _auth if k[0] == room["key"]]:
        _auth.pop(k, None)  # the match is over, so cached permissions are void
    for slot in ("p1", "p2"):
        key = stream_key(room["key"], st["gen"], slot)
        _created.discard(key)
        _lastn.pop(key, None)
        try:
            store.delete(key)
        except Exception as exc:  # a missing record is fine
            print(f"[brawl] drop {key}: {exc}")


def register(app, get_store, find, fail, now):
    def upsert(key, doc):
        """Create the record the first time, update it after. Survives a server restart."""
        store = get_store()
        if key in _created:
            try:
                store.put(key, doc)
                return
            except ShadeError as exc:
                if exc.code.startswith("HTTP_"):
                    raise
        try:
            store.put(key, doc, new=True)
        except ShadeError as exc:
            if exc.code != "ERR_STORAGE_CONSTRAINT_VIOLATION":
                raise
            store.put(key, doc)
        _created.add(key)

    def verify(key, token, gen):
        """Return (slot, None) or (None, (status, message)). Cached briefly so a sync is not two reads."""
        hit = _auth.get((key, token))
        if hit and hit["gen"] == gen and time.time() < hit["until"]:
            return hit["slot"], None
        room, slot = find(key, token)
        if not room:
            return None, (404, "This room was closed.")
        if not slot:
            return None, (403, "You are not in this room.")
        st = room["state"]
        if room["game"] != "brawl" or room["status"] != "active" or st.get("phase") != "fight":
            return None, (409, "The match is not running.")
        if gen != st["gen"]:
            return None, (409, "That match has ended.")
        if len(_auth) > 400:
            for k in [k for k, v in _auth.items() if v["until"] < time.time()]:
                _auth.pop(k, None)
        _auth[(key, token)] = dict(slot=slot, gen=gen, until=time.time() + 15)
        return slot, None

    def timed(fn):
        t = time.perf_counter()
        out = fn()
        return out, (time.perf_counter() - t) * 1000

    @app.post("/api/brawl/sync")
    def brawl_sync():
        d = request.get_json(silent=True) or {}
        key, token, gen = d.get("key"), d.get("token"), d.get("gen")
        slot, err = verify(key, token, gen)
        if err:
            return fail(err[1], err[0])
        rec = d.get("rec")
        if rec is not None and (not isinstance(rec, dict) or len(json.dumps(rec, separators=(",", ":"))) > MAX_REC):
            return fail("That update is too large.", 413)
        mine, theirs = stream_key(key, gen, slot), stream_key(key, gen, "p2" if slot == "p1" else "p1")

        def write():
            if rec is None:
                return None
            n = rec.get("n") if isinstance(rec.get("n"), (int, float)) else 0
            with _lock:
                if n and n <= _lastn.get(mine, 0):
                    return None  # an older update that arrived late: the newer one already won
                _lastn[mine] = max(n, _lastn.get(mine, 0))
            upsert(mine, dict(rec, rev=int(n), updated=now()))

        w, r = POOL.submit(timed, write), POOL.submit(timed, lambda: get_store().get(theirs))
        (_, w_ms), (opp, r_ms) = w.result(), r.result()
        resp = jsonify(opp=opp, t=time.time() * 1000, slot=slot, db=dict(w=round(w_ms, 1), r=round(r_ms, 1)))
        resp.headers["Cache-Control"] = "no-store"
        return resp
