"""Heaven Brawl: real-time arcade fighting.

The room record only holds the slow stuff: who picked which fighter, and the final
result. The fight itself is played in the browser and travels between the players as
small, frequent updates (see realtime.py), still carried only by shadeDB. Because that
is inherently laggy, the game checks the connection before a match and lets each
player decide whether to play.
"""
import random
import secrets

TITLE = "Heaven Brawl"
BLURB = "Real-time arcade fighting. We check your connection first, and you decide whether to play."
ROUNDS_TO_WIN = 2
CLASSES = {
    "paladin": dict(title="Paladin", special="Shield Bash", blurb="Heavy and tough. Bashes forward through a guard."),
    "seraph": dict(title="Seraph", special="Fireball", blurb="Keeps its distance and throws fire."),
    "valkyrie": dict(title="Valkyrie", special="Spear Thrust", blurb="The longest reach in the arena."),
    "cherub": dict(title="Cherub", special="Dash Strike", blurb="Fast and slippery, hits in a rush."),
}


def new_state(first="p1"):
    return dict(phase="pick", picks={"p1": None, "p2": None}, gen=secrets.randbits(31),
                wins={"p1": 0, "p2": 0}, turn=None)


def can_act(state, slot):
    """Picking happens once each. The fight is real time, so both players are always 'on'."""
    return state["picks"][slot] is None if state["phase"] == "pick" else True


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
            state["phase"] = "fight"
            p = state["picks"]
            return None, [f"{names['p1']} the {CLASSES[p['p1']]['title']} faces "
                          f"{names['p2']} the {CLASSES[p['p2']]['title']}."], None
        return None, [], None
    fin = move.get("finish")  # the host reports the final result when the match is decided
    if not isinstance(fin, dict):
        return "The fight is played live in the arena.", [], None
    if slot != "p1":
        return "Only the host reports the result.", [], None
    winner = fin.get("winner")
    if winner not in ("p1", "p2", "draw"):
        return "Unknown result.", [], None
    wins = fin.get("wins") if isinstance(fin.get("wins"), dict) else {}
    state["wins"] = {s: max(0, min(ROUNDS_TO_WIN, int(wins.get(s, 0) or 0))) for s in ("p1", "p2")}
    w = state["wins"]
    return None, [], dict(winner=winner, text=f"Best of three, {w['p1']} to {w['p2']}" if winner != "draw" else "Draw")


def bot_move(state, slot):
    """The computer opponent plays in the browser, not here. It only picks a fighter."""
    return {"pick": random.choice(list(CLASSES))} if state["phase"] == "pick" else None


def view_state(state, viewer):
    op = "p2" if viewer == "p1" else "p1"
    fighting = state["phase"] == "fight"
    return dict(phase=state["phase"], turn=None, gen=state["gen"], wins=state["wins"], rounds=ROUNDS_TO_WIN,
                my_pick=state["picks"][viewer], opp_picked=state["picks"][op] is not None,
                me=state["picks"][viewer] if fighting else None, opp=state["picks"][op] if fighting else None)
