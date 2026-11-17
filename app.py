"""Heaven Duels: chess and snakes & ladders, with shadeDB as the multiplayer layer.

No websockets, no server push. Every client simply asks the database what the
room looks like (GET /api/room/<key>) and renders the answer. A move is one
write to the room record, and the opponent's next poll sees it.
"""
import hashlib
import hmac
import os
import random
import re
import secrets
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

import bench  # noqa: E402
import clans  # noqa: E402
import realtime  # noqa: E402
from games import GAMES, brawl, fight, snakes  # noqa: E402
from store import ShadeError, make_store  # noqa: E402

VERSION = "1.1.0"
LINKS = dict(x="https://x.com/shade_ofc", shadedb="https://shadedb.duckdns.org")

ONLINE_WINDOW, CLAIM_AFTER = 20, 45
EMOTES = ("👍", "👏", "🔥", "😮", "😂", "😎", "🙏", "😢", "❤️", "💀")
BOT_NAMES = ("Archon Raziel", "Archon Ophan", "Archon Sariel", "Archon Zadkiel")

app = Flask(__name__, static_folder="static")
app.json.sort_keys = False  # keep the order games are listed in
store = make_store(BASE)
_locks, _glock = {}, threading.Lock()


def now():
    return int(time.time())


DEMO_MARK = "# created by start.sh: shared demo database"


def uses_demo_env():
    """True when .env is the one start.sh wrote for the shared demo database."""
    try:
        return DEMO_MARK in (BASE / ".env").read_text()
    except OSError:
        return False


def build_id():
    """Changes whenever the front end changes, so open pages can refresh themselves."""
    files = [(BASE / "static" / n).stat() for n in ("index.html", "brawl.js") if (BASE / "static" / n).exists()]
    return "-".join(f"{int(s.st_mtime)}.{s.st_size}" for s in files)


def room_lock(key):
    with _glock:
        return _locks.setdefault(key, threading.Lock())


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")[:24]


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), 120_000).hex()}"


def check_pw(pw, stored):
    return hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)


def fail(msg, code=400):
    return jsonify(error=msg), code


def clean(text, limit):
    return re.sub(r"[\x00-\x1f]+", " ", text or "").strip()[:limit]


def new_player(name, bot=False):
    p = dict(name=name, token=secrets.token_hex(12), seen=now())
    if bot:
        p["bot"] = True
    return p


def other(slot):
    return "p2" if slot == "p1" else "p1"


def names(room):
    return {s: (p["name"] if p else "") for s, p in room["players"].items()}


def save(room, new=False):
    room["rev"] += 1
    room["updated"] = now()
    store.put(room["key"], room, new=new)


def find(key, token):
    """Return (room, slot). slot is None if the token is not in the room."""
    room = store.get(key or "")
    if not room:
        return None, None
    for slot, p in room["players"].items():
        if p and hmac.compare_digest(p["token"], token or ""):
            return room, slot
    return room, None


def record(room, lines, end):
    """Log what happened and close the game if it ended."""
    if lines:
        room["log"] = (room["log"] + [dict(lines=lines)])[-20:]
    if end:
        room["status"], room["winner"], room["result"] = "done", end["winner"], end["text"]
        if end["winner"] in ("p1", "p2"):
            room["score"][end["winner"]] += 1


def can_act(room, slot):
    """Whose move is it? Turn-based games say so in `turn`; simultaneous games define can_act."""
    mod, st = GAMES[room["game"]], room["state"]
    return room["status"] == "active" and (mod.can_act(st, slot) if hasattr(mod, "can_act") else st["turn"] == slot)


def run_bot(room):
    """Let the computer (always p2) play until it is a human's turn."""
    for _ in range(30):
        if not room.get("bot") or not can_act(room, "p2"):
            return
        mod, st = GAMES[room["game"]], room["state"]
        move = mod.bot_move(st, "p2")
        if move is None:  # this game's computer opponent plays in the browser
            return
        err, lines, end = mod.apply(st, "p2", move, names(room))
        if err:
            return
        record(room, lines, end)


def view(room, slot):
    """What this client may see."""
    opp = room["players"][other(slot)]
    bot = bool(opp and opp.get("bot"))
    st = room["state"]
    return dict(
        room=room["name"], game=room["game"], locked=bool(room["pw"]), status=room["status"],
        winner=room["winner"], result=room.get("result"), you=slot, rev=room["rev"], score=room["score"],
        vs_bot=bot, names=names(room), opponent_online=bool(opp) and (bot or now() - opp["seen"] < ONLINE_WINDOW),
        my_turn=can_act(room, slot), host=slot == "p1", delete_on_leave=room.get("delete_on_leave", True),
        can_claim=room["status"] == "active" and bool(opp) and not bot and now() - opp["seen"] > CLAIM_AFTER,
        rematch=dict(me=room["rematch"][slot], opponent=room["rematch"][other(slot)]),
        reactions=room.get("reactions", [])[-6:], chat=room.get("chat", [])[-40:], log=room["log"][-14:],
        state=GAMES[room["game"]].view_state(st, slot), build=build_id(),
    )


@app.get("/api/meta")
def meta():
    return jsonify(games={k: dict(title=m.TITLE, blurb=m.BLURB) for k, m in GAMES.items()},
                   board=dict(ladders=snakes.LADDERS, snakes=snakes.SNAKES),
                   fight=dict(classes=fight.CLASSES, moves=fight.MOVES, rules=fight.RULES),
                   brawl=dict(classes=brawl.CLASSES, rounds=brawl.ROUNDS_TO_WIN),
                   emotes=EMOTES, backend=store.name, online=store.online, build=build_id(),
                   version=VERSION, links=LINKS, demo=bool(store.online and uses_demo_env()))


@app.post("/api/create")
def create():
    d = request.get_json(force=True)
    game, bot = d.get("game"), bool(d.get("bot"))
    if game not in GAMES:
        return fail("Pick a game.")
    room_name = clean(d.get("room"), 24)
    if bot and not room_name:
        room_name = "Practice " + secrets.token_hex(2)
    slug = slugify(room_name)
    if len(slug) < 3:
        return fail("Room names need at least 3 letters or numbers.")
    key = "hd_" + slug
    first = {"black": "p2", "random": random.choice(("p1", "p2"))}.get(d.get("color"), "p1") \
        if game == "chess" else "p1"
    with room_lock(key):
        old = store.get(key)
        if old and old["status"] != "done" and now() - old["updated"] < 6 * 3600:
            return fail("That room name is taken. Pick another.", 409)
        pw = d.get("password") or ""
        me = new_player(clean(d.get("name"), 16) or "Wanderer")
        room = dict(key=key, name=room_name, pw=hash_pw(pw) if pw else None, game=game, status="waiting",
                    winner=None, result=None, rev=0, updated=now(), players={"p1": me, "p2": None},
                    state=GAMES[game].new_state(first), first=first, score={"p1": 0, "p2": 0},
                    rematch={"p1": False, "p2": False}, emote=None, chat=[], log=[], bot=bot,
                    delete_on_leave=bool(d.get("delete_on_leave", True)))
        if bot:
            room["players"]["p2"], room["status"] = new_player(random.choice(BOT_NAMES), bot=True), "active"
            run_bot(room)
        print(f"[room] {key} created ({game}{', vs computer' if bot else ''})")
        try:
            save(room, new=old is None)
        except ShadeError as exc:  # lost a race: the unique `room` field already exists
            if exc.code == "ERR_STORAGE_CONSTRAINT_VIOLATION":
                return fail("That room name is taken. Pick another.", 409)
            raise
    return jsonify(key=key, token=me["token"], slot="p1")


@app.post("/api/join")
def join():
    d = request.get_json(force=True)
    key = "hd_" + slugify(d.get("room") or "")
    with room_lock(key):
        room = store.get(key)
        if not room:
            return fail("No room with that name.", 404)
        if room["pw"] and not check_pw(d.get("password") or "", room["pw"]):
            return fail("Wrong room password.", 403)
        if room["players"]["p2"]:
            return fail("That room is full.", 409)
        me = new_player(clean(d.get("name"), 16) or "Wanderer")
        room["players"]["p2"], room["status"] = me, "active"
        record(room, [f"{me['name']} joins. Let the game begin."], None)
        print(f"[room] {key} joined by {me['name']}")
        save(room)
    return jsonify(key=key, token=me["token"], slot="p2")


@app.get("/api/room/<key>")
def poll(key):
    room, slot = find(key, request.args.get("token"))
    if not room:
        return fail("This room was closed.", 404)
    if not slot:
        return fail("You are not in this room.", 403)
    if now() - room["players"][slot]["seen"] > 8:  # heartbeat: tells the opponent we are here
        with room_lock(key):
            room, slot = find(key, request.args.get("token"))
            room["players"][slot]["seen"] = now()
            store.put(key, room)
    return jsonify(view(room, slot))


def locked_action(fn):
    """Shared plumbing: parse body, lock the room, authenticate, run fn(room, slot, body)."""
    def handler():
        d = request.get_json(force=True)
        with room_lock(d.get("key")):
            room, slot = find(d.get("key"), d.get("token"))
            if not room:
                return fail("This room was closed.", 404)
            if not slot:
                return fail("You are not in this room.", 403)
            res = fn(room, slot, d)
            if res is not None:
                return res
            save(room)
            return jsonify(view(room, slot))
    handler.__name__ = fn.__name__
    return handler


@app.post("/api/move")
@locked_action
def move(room, slot, d):
    if room["status"] != "active":
        return fail("The game is not active.", 409)
    err, lines, end = GAMES[room["game"]].apply(room["state"], slot, d.get("move") or {}, names(room))
    if err:
        return fail(err)
    record(room, lines, end)
    if end and room["game"] == "brawl":
        realtime.drop(store, room)
    run_bot(room)


@app.post("/api/leave")
def leave():
    """Leave a room. The host decides, when creating it, whether leaving also deletes it."""
    d = request.get_json(force=True)
    key = d.get("key")
    with room_lock(key):
        room, slot = find(key, d.get("token"))
        if not slot:
            return jsonify(ok=True, deleted=False)  # already gone
        name = room["players"][slot]["name"]
        if room.get("bot") or room.get("host_left") or (slot == "p1" and room.get("delete_on_leave", True)):
            realtime.drop(store, room)
            store.delete(key)
            print(f"[room] {key} deleted when {name} left")
            return jsonify(ok=True, deleted=True)
        if slot == "p1":  # the host leaves but keeps the room: the guest finishes up and closes it
            room["host_left"] = True
            end = dict(winner="p2", text="Host left") if room["status"] == "active" else None
            record(room, [f"{name} (host) left the room."], end)
        else:  # a guest leaves: the seat opens up for someone else
            room.update(status="waiting", winner=None, result=None, score={"p1": 0, "p2": 0},
                        rematch={"p1": False, "p2": False}, state=GAMES[room["game"]].new_state(room["first"]),
                        log=[dict(lines=[f"{name} left the room."])])
            room["players"]["p2"] = None
        save(room)
        return jsonify(ok=True, deleted=False)


@app.post("/api/resign")
@locked_action
def resign(room, slot, d):
    if room["status"] != "active":
        return fail("The game is not active.", 409)
    record(room, [f"{room['players'][slot]['name']} resigns."], dict(winner=other(slot), text="Resignation"))


@app.post("/api/draw")
@locked_action
def draw(room, slot, d):
    mod = GAMES[room["game"]]
    if room["status"] != "active" or not hasattr(mod, "offer_draw"):
        return fail("Draws are not available here.", 409)
    if room.get("bot"):
        return fail("The computer declines a draw.", 409)
    err, lines, end = mod.offer_draw(room["state"], slot, names(room))
    record(room, lines, end)


@app.post("/api/chat")
@locked_action
def chat(room, slot, d):
    text = clean(d.get("text"), 200)
    if not text:
        return fail("Say something first.")
    log = room.setdefault("chat", [])
    mine = [m for m in log if m["s"] == slot]
    if mine and now() - mine[-1]["t"] < 1:
        return fail("Slow down a little.", 429)
    log.append(dict(i=(log[-1].get("i", 0) + 1) if log else 1, s=slot, n=room["players"][slot]["name"], t=now(), x=text))
    room["chat"] = log[-40:]


@app.post("/api/emote")
@locked_action
def emote(room, slot, d):
    if d.get("emote") not in EMOTES:
        return fail("Nope.", 403)
    log = room.get("reactions", [])
    mine = [r for r in log if r["s"] == slot]
    if mine and time.time() - mine[-1]["ms"] < 0.4:
        return fail("Easy there.", 429)
    log.append(dict(n=(log[-1]["n"] + 1) if log else 1, s=slot, e=d["emote"], t=now(), ms=time.time()))
    room["reactions"] = log[-6:]


@app.post("/api/rematch")
@locked_action
def rematch(room, slot, d):
    if room["status"] != "done":
        return fail("Nothing to rematch.", 409)
    room["rematch"][slot] = True
    if room.get("bot"):
        room["rematch"]["p2"] = True
    if all(room["rematch"].values()):
        realtime.drop(store, room)
        room["first"] = other(room["first"])  # swap who starts / plays white
        room.update(status="active", winner=None, result=None, rematch={"p1": False, "p2": False},
                    state=GAMES[room["game"]].new_state(room["first"]), log=[dict(lines=["A new game begins."])])
        run_bot(room)


@app.post("/api/claim")
@locked_action
def claim(room, slot, d):
    if not view(room, slot)["can_claim"]:
        return fail("Your opponent is still around.", 409)
    record(room, [f"{room['players'][slot]['name']} claims the win. The opponent left."],
           dict(winner=slot, text="Opponent left"))


@app.errorhandler(Exception)
def oops(exc):
    if isinstance(exc, HTTPException):  # 404s and friends are not server errors
        return (jsonify(error=exc.name), exc.code) if request.path.startswith("/api/") else exc
    print(f"[error] {exc!r}")
    if isinstance(exc, ShadeError):
        return fail(f"The database said {exc.code}. Try again in a moment.", 503)
    return fail("Something went wrong on the server. Try again.", 500)


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory("static", "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


clans.register(app, lambda: store, room_lock, clean, now, fail, GAMES)
bench.register(app, lambda: store, fail, now)
realtime.register(app, lambda: store, find, fail, now)


if __name__ == "__main__":
    print(f"Heaven Duels: storage = {store.name}")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            threaded=True)
