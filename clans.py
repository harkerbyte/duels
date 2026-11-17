"""Clans: a persistent group with a unique cable ID, a member list that remembers who
joined and left, and a chat. Like rooms, a clan is one record in shadeDB, and members
simply ask the database what changed. No accounts: a member is a token this device holds."""
import hmac
import re
import secrets

from flask import jsonify, request

from store import ShadeError

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I or L, which are easy to mix up
MAX_MEMBERS, ONLINE_WINDOW = 40, 20


def cable_id():
    s = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return s[:4] + "-" + s[4:]


def normalise(raw):
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    return s[:4] + "-" + s[4:] if len(s) == 8 else None


def key_of(cid):
    return "cl_" + cid.replace("-", "").lower()


def register(app, get_store, room_lock, clean, now, fail, games):
    def event(clan, kind, name):
        clan["history"] = (clan["history"] + [dict(t=now(), e=kind, n=name)])[-60:]

    def save(clan, new=False):
        clan["rev"] += 1
        clan["updated"] = now()
        get_store().put(clan["key"], clan, new=new)

    def find(cid, token):
        """Return (clan, member id). The member id is None when the token does not belong here."""
        cid = normalise(cid)
        clan = get_store().get(key_of(cid)) if cid else None
        if not clan:
            return None, None
        for mid, m in clan["members"].items():
            if hmac.compare_digest(m["tok"], token or ""):
                return clan, mid
        return clan, None

    def view(clan, mid):
        members = [dict(m=k, n=v["n"], online=now() - v["seen"] < ONLINE_WINDOW, owner=k == clan["owner"],
                        joined=v["j"]) for k, v in clan["members"].items()]
        members.sort(key=lambda m: (not m["owner"], m["joined"]))
        return dict(id=clan["id"], name=clan["name"], you=mid, owner=clan["owner"] == mid, members=members,
                    history=clan["history"][-25:], chat=clan["chat"][-60:], rev=clan["rev"],
                    created=clan["created"])

    def member_action(fn):
        """Parse the body, lock the clan, authenticate the member, run fn(clan, mid, body)."""
        def handler():
            d = request.get_json(force=True)
            cid = normalise(d.get("id"))
            if not cid:
                return fail("That is not a valid cable ID.", 400)
            with room_lock(key_of(cid)):
                clan, mid = find(cid, d.get("token"))
                if not clan:
                    return fail("This clan no longer exists.", 404)
                if not mid:
                    return fail("You are not in this clan.", 403)
                res = fn(clan, mid, d)
                if res is not None:
                    return res
                save(clan)
                return jsonify(view(clan, mid))
        handler.__name__ = fn.__name__
        return handler

    @app.post("/api/clan/create")
    def clan_create():
        d = request.get_json(force=True)
        name, nick = clean(d.get("name"), 24), clean(d.get("nick"), 16) or "Wanderer"
        if len(name) < 3:
            return fail("A clan name needs at least 3 characters.")
        for _ in range(6):
            cid = cable_id()
            key = key_of(cid)
            with room_lock(key):
                if get_store().get(key):
                    continue
                mid, tok = secrets.token_hex(3), secrets.token_hex(12)
                clan = dict(key=key, id=cid, name=name, created=now(), rev=0, updated=now(), owner=mid,
                            members={mid: dict(n=nick, tok=tok, j=now(), seen=now())}, history=[], chat=[])
                event(clan, "created", nick)
                try:
                    save(clan, new=True)
                except ShadeError as exc:
                    if exc.code == "ERR_STORAGE_CONSTRAINT_VIOLATION":
                        continue
                    raise
                print(f"[clan] {key} created: {name}")
                return jsonify(id=cid, name=name, token=tok, mid=mid)
        return fail("Could not allocate a cable ID. Try again.", 503)

    @app.post("/api/clan/join")
    def clan_join():
        d = request.get_json(force=True)
        cid = normalise(d.get("id"))
        if not cid:
            return fail("A cable ID looks like K7QM-X2NA.")
        nick = clean(d.get("nick"), 16) or "Wanderer"
        with room_lock(key_of(cid)):
            clan = get_store().get(key_of(cid))
            if not clan:
                return fail("No clan has that cable ID.", 404)
            if len(clan["members"]) >= MAX_MEMBERS:
                return fail("That clan is full.", 409)
            mid, tok = secrets.token_hex(3), secrets.token_hex(12)
            clan["members"][mid] = dict(n=nick, tok=tok, j=now(), seen=now())
            event(clan, "joined", nick)
            save(clan)
            print(f"[clan] {clan['key']} joined by {nick}")
            return jsonify(id=cid, name=clan["name"], token=tok, mid=mid)

    @app.get("/api/clan/<cid>")
    def clan_poll(cid):
        clan, mid = find(cid, request.args.get("token"))
        if not clan:
            return fail("This clan no longer exists.", 404)
        if not mid:
            return fail("You are not in this clan.", 403)
        if now() - clan["members"][mid]["seen"] > 8:  # heartbeat, so others see you online
            with room_lock(clan["key"]):
                clan, mid = find(cid, request.args.get("token"))
                if clan and mid:
                    clan["members"][mid]["seen"] = now()
                    get_store().put(clan["key"], clan)
        return jsonify(view(clan, mid))

    @app.post("/api/clan/chat")
    @member_action
    def clan_chat(clan, mid, d):
        text = clean(d.get("text"), 200)
        inv = d.get("invite") if isinstance(d.get("invite"), dict) else None
        room, game = clean((inv or {}).get("room"), 24), (inv or {}).get("game")
        if inv and (game not in games or len(re.sub(r"[^a-z0-9]", "", room.lower())) < 3):
            inv = None
        if inv:
            text = text or f'Join my {games[game].TITLE} room "{room}"'
        if not text:
            return fail("Say something first.")
        log = clan["chat"]
        mine = [m for m in log if m["m"] == mid]
        if mine and now() - mine[-1]["t"] < 1:
            return fail("Slow down a little.", 429)
        entry = dict(i=(log[-1]["i"] + 1) if log else 1, m=mid, n=clan["members"][mid]["n"], t=now(), x=text)
        if inv:
            entry["inv"] = dict(room=room, game=game)
        clan["chat"] = (log + [entry])[-80:]

    @app.post("/api/clan/leave")
    def clan_leave():
        d = request.get_json(force=True)
        cid = normalise(d.get("id"))
        if not cid:
            return jsonify(ok=True)
        with room_lock(key_of(cid)):
            clan, mid = find(cid, d.get("token"))
            if not clan or not mid:
                return jsonify(ok=True)  # already gone
            name = clan["members"].pop(mid)["n"]
            if not clan["members"]:
                get_store().delete(clan["key"])
                return jsonify(ok=True, deleted=True)
            event(clan, "left", name)
            if clan["owner"] == mid:  # hand the clan to whoever has been in it longest
                clan["owner"] = min(clan["members"], key=lambda k: clan["members"][k]["j"])
                event(clan, "owner", clan["members"][clan["owner"]]["n"])
            save(clan)
            return jsonify(ok=True, deleted=False)

    @app.post("/api/clan/disband")
    def clan_disband():
        d = request.get_json(force=True)
        cid = normalise(d.get("id"))
        if not cid:
            return fail("That is not a valid cable ID.")
        with room_lock(key_of(cid)):
            clan, mid = find(cid, d.get("token"))
            if not clan:
                return jsonify(ok=True)
            if not mid or clan["owner"] != mid:
                return fail("Only the clan owner can disband it.", 403)
            get_store().delete(clan["key"])
            return jsonify(ok=True, deleted=True)
