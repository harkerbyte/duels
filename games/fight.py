"""Heaven Fighters: a simultaneous-move duel.

Both players choose in secret and the round resolves when the second choice lands,
so the database never has to deliver anything faster than a human can think. Each
player first picks one of four fighters, then they trade rounds of Strike, Guard,
Mend, Channel, an ability, and Judgment once Grace is full.
"""
import random

TITLE = "Heaven Fighters"
BLURB = "Pick a fighter, lock in a move in secret, and clash. Read your opponent."
MAX_MP, REGEN = 100, 6
GUARD_TAKES, GUARD_MP = 0.3, 10
MEND_COST, MEND_HEAL = 15, 20
CHANNEL_MP, CHARGE_MULT, VULN_MULT = 25, 1.4, 1.25
GRACE_MAX, JUDGMENT_DMG = 5, 40
BURN_DMG, BURN_TURNS = 3, 3

CLASSES = {
    "paladin": dict(title="Paladin", hp=120, mp=40, atk=(10, 14), ability="Radiant Bulwark", cost=20,
                    blurb="Sturdy. Strikes for 8 and raises a 25 point shield that protects you this round."),
    "seraph": dict(title="Seraph", hp=85, mp=70, atk=(7, 11), ability="Smite Flame", cost=25,
                   blurb="Fragile, rich in MP. Strikes for 20 and sets the target burning for 3 a round, 3 rounds."),
    "valkyrie": dict(title="Valkyrie", hp=100, mp=45, atk=(11, 16), ability="Skyfall Lance", cost=25,
                     blurb="Hard hitter. Strikes for 24, and 50% more if the target is channelling."),
    "cherub": dict(title="Cherub", hp=90, mp=50, atk=(9, 13), ability="Feint", cost=20,
                   blurb="Trickster. Strikes for 15 through a guard and steals 10 MP."),
}
MOVES = {
    "strike": dict(label="Strike", desc="Reliable damage"),
    "guard": dict(label="Guard", desc="Take 70% less from attacks. +10 MP"),
    "mend": dict(label="Mend", desc="+20 HP, puts out burning. 15 MP"),
    "channel": dict(label="Channel", desc="+25 MP, next attack +40%. You take 25% more this round"),
    "ability": dict(label="Ability", desc="Your fighter's special move"),
    "judgment": dict(label="Judgment", desc="40 damage through guard. Needs 5 Grace"),
}
OFFENSIVE = ("strike", "ability", "judgment")
RULES = dict(mend_cost=MEND_COST, grace_max=GRACE_MAX, max_mp=MAX_MP)


def new_fighter(cls):
    c = CLASSES[cls]
    return dict(cls=cls, hp=c["hp"], max_hp=c["hp"], mp=c["mp"], shield=0, grace=0, charged=False, burn=0)


def new_state(first="p1"):
    return dict(phase="pick", picks={"p1": None, "p2": None}, fighters=None, moves={"p1": None, "p2": None},
                round=1, n=0, last=None, turn=None)


def can_act(state, slot):
    """Both players act at once, so there is no turn: you can act until you have locked in."""
    if state["phase"] == "pick":
        return state["picks"][slot] is None
    return state["moves"][slot] is None


def move_cost(f, move):
    if move == "ability":
        return CLASSES[f["cls"]]["cost"]
    return MEND_COST if move == "mend" else 0


def move_error(f, move):
    if move not in MOVES:
        return "Unknown move."
    if f["mp"] < move_cost(f, move):
        return "Not enough MP."
    if move == "judgment" and f["grace"] < GRACE_MAX:
        return "Judgment needs full Grace."
    return None


def label(f, move):
    return CLASSES[f["cls"]]["ability"] if move == "ability" else MOVES[move]["label"]


def apply(state, slot, move, names):
    """Returns (error, log_lines, end). Never mutates state when it returns an error."""
    if state["phase"] == "pick":
        cls = move.get("pick")
        if cls not in CLASSES:
            return "Choose a fighter.", [], None
        if state["picks"][slot]:
            return "You already chose a fighter.", [], None
        state["picks"][slot] = cls
        if all(state["picks"].values()):
            state["fighters"] = {s: new_fighter(c) for s, c in state["picks"].items()}
            state["phase"] = "fight"
            p = state["picks"]
            return None, [f"{names['p1']} the {CLASSES[p['p1']]['title']} faces "
                          f"{names['p2']} the {CLASSES[p['p2']]['title']}."], None
        return None, [], None
    m = move.get("move")
    err = move_error(state["fighters"][slot], m)
    if err:
        return err, [], None
    if state["moves"][slot]:
        return "Move already locked in.", [], None
    state["moves"][slot] = m
    if all(state["moves"].values()):
        return _resolve(state, names)
    return None, [], None


def _resolve(state, names):
    P, M, nm = state["fighters"], state["moves"], names
    foe = {"p1": "p2", "p2": "p1"}
    lines = [f"{nm['p1']} chose {label(P['p1'], M['p1'])}. {nm['p2']} chose {label(P['p2'], M['p2'])}."]

    atk = {}
    for s, p in P.items():
        m = M[s]
        mult = CHARGE_MULT if p["charged"] and m in OFFENSIVE else 1
        a = dict(dmg=0, pierce=False, burn=False, steal=0, vs_channel=1.0)
        if m == "strike":
            a["dmg"] = random.randint(*CLASSES[p["cls"]]["atk"]) * mult
        elif m == "judgment":
            a.update(dmg=JUDGMENT_DMG * mult, pierce=True)
        elif m == "ability":
            k = p["cls"]
            if k == "paladin":
                a["dmg"] = 8 * mult
            elif k == "seraph":
                a.update(dmg=20 * mult, burn=True)
            elif k == "valkyrie":
                a.update(dmg=24 * mult, vs_channel=1.5)
            elif k == "cherub":
                a.update(dmg=15 * mult, pierce=True, steal=10)
        atk[s] = a

    for s, p in P.items():  # self effects
        m = M[s]
        p["mp"] -= move_cost(p, m)
        if m == "guard":
            p["mp"] += GUARD_MP
        elif m == "channel":
            p["mp"] += CHANNEL_MP
        elif m == "mend":
            p["hp"] = min(p["max_hp"], p["hp"] + MEND_HEAL)
            if p["burn"]:
                lines.append(f"{nm[s]}'s flames are put out.")
            p["burn"] = 0
        elif m == "ability" and p["cls"] == "paladin":
            p["shield"] += 25
        if m in OFFENSIVE:
            p["charged"] = False
        if m == "channel":
            p["charged"] = True
        if m == "judgment":
            p["grace"] = 0

    took = {"p1": 0, "p2": 0}
    ignite = []
    for s, o in foe.items():
        a, d, how = atk[s], atk[s]["dmg"], label(P[s], M[s])
        if d <= 0:
            continue
        guarded = M[o] == "guard" and not a["pierce"]
        if guarded:
            d *= GUARD_TAKES
        if M[o] == "channel":
            d *= VULN_MULT * a["vs_channel"]
        d = round(d)
        if d <= 0:
            lines.append(f"{nm[o]} fully blocks {how}.")
            continue
        absorbed = min(P[o]["shield"], d)
        P[o]["shield"] -= absorbed
        P[o]["hp"] = max(0, P[o]["hp"] - (d - absorbed))
        took[o] += d
        lines.append(f"{nm[s]}'s {how} hits {nm[o]} for {d}" + (" (guarded)" if guarded else "")
                     + (f", {absorbed} absorbed" if absorbed else "") + ".")
        if a["burn"] and not guarded:
            ignite.append(o)
        if a["steal"]:
            stolen = min(a["steal"], P[o]["mp"])
            P[o]["mp"] -= stolen
            P[s]["mp"] += stolen
            if stolen:
                lines.append(f"{nm[s]} steals {stolen} MP.")

    for s, p in P.items():  # burning ticks
        if p["burn"] > 0:
            p["hp"] = max(0, p["hp"] - BURN_DMG)
            p["burn"] -= 1
            took[s] += BURN_DMG
            lines.append(f"{nm[s]} burns for {BURN_DMG}.")
    for o in ignite:
        P[o]["burn"] = BURN_TURNS
        lines.append(f"{nm[o]} catches fire.")

    for s, p in P.items():  # grace and mana
        p["grace"] = min(GRACE_MAX, p["grace"] + 1 + (1 if took[s] else 0))
        p["mp"] = max(0, min(MAX_MP, p["mp"] + REGEN))

    state["last"] = dict(round=state["round"], moves=dict(M), lines=list(lines))
    state["n"] += 1
    state["moves"] = {"p1": None, "p2": None}
    h1, h2 = P["p1"]["hp"], P["p2"]["hp"]
    if h1 <= 0 or h2 <= 0:
        winner = "draw" if h1 <= 0 and h2 <= 0 else ("p1" if h2 <= 0 else "p2")
        lines.append("Both fighters fall." if winner == "draw" else f"{nm[winner]} wins the duel.")
        return None, lines, dict(winner=winner, text="Double knockout" if winner == "draw" else "Knockout")
    state["round"] += 1
    return None, lines, None


def bot_move(state, slot):
    """The computer: greedy with a little unpredictability."""
    if state["phase"] == "pick":
        return {"pick": random.choice(list(CLASSES))}
    b, h = state["fighters"][slot], state["fighters"]["p1" if slot == "p2" else "p2"]
    legal = [m for m in MOVES if move_error(b, m) is None]
    if "judgment" in legal:
        return {"move": "judgment"}
    w = {m: 1.0 for m in legal}
    w["strike"] = 3
    if "ability" in w:
        w["ability"] = 2.5
    if "mend" in w and b["hp"] < b["max_hp"] * 0.4:
        w["mend"] = 5
    if "guard" in w and (h["charged"] or h["grace"] >= GRACE_MAX):
        w["guard"] = 5
    if "channel" in w and b["mp"] < 30:
        w["channel"] = 3
    return {"move": random.choices(list(w), weights=list(w.values()))[0]}


def _pub(f):
    return {k: f[k] for k in ("cls", "hp", "max_hp", "mp", "shield", "grace", "charged", "burn")}


def view_state(state, viewer):
    """What this player may see. The opponent's fighter stays hidden until both have chosen,
    and a pending move is never sent: only whether the opponent has locked in."""
    op = "p2" if viewer == "p1" else "p1"
    f = state["fighters"]
    return dict(phase=state["phase"], round=state["round"], n=state["n"], turn=None,
                my_pick=state["picks"][viewer], opp_picked=state["picks"][op] is not None,
                me=_pub(f[viewer]) if f else None, opp=_pub(f[op]) if f else None,
                my_move=state["moves"][viewer], opp_ready=state["moves"][op] is not None,
                last=state["last"])
