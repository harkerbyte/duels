"""Snakes and Ladders (stairways and serpents). Server-side dice, so nobody can cheat.

Rules: first to land exactly on 100 wins. A roll that overshoots 100 is wasted.
Rolling a six gives another turn. Ladders carry you up, serpents slide you down.
"""
import random

TITLE = "Snakes & Ladders"
BLURB = "Race to 100. Climb the stairways, dodge the serpents."
LADDERS = {1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100}
SNAKES = {16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78}


def new_state(first="p1"):
    return dict(pos={"p1": 0, "p2": 0}, turn=first, last=None, n=0)


def apply(state, slot, move, names):
    """Returns (error, log_lines, end). Never mutates state when it returns an error."""
    if state["turn"] != slot:
        return "It is not your turn.", [], None
    roll = random.randint(1, 6)
    start = state["pos"][slot]
    target = start + roll
    who = names[slot]
    kind, landed = None, start
    if target > 100:
        text = f"{who} rolled {roll} but needs the exact number to reach 100."
        end_sq = start
    else:
        landed = end_sq = target
        text = f"{who} rolled {roll} and moves to {target}"
        if target in LADDERS:
            end_sq, kind = LADDERS[target], "ladder"
            text += f", climbs a stairway to {end_sq}"
        elif target in SNAKES:
            end_sq, kind = SNAKES[target], "snake"
            text += f", is bitten by a serpent and slides to {end_sq}"
        text += "."
    state["pos"][slot] = end_sq
    state["n"] += 1
    state["last"] = dict(slot=slot, roll=roll, start=start, landed=landed, end=end_sq, kind=kind)
    lines = [text]
    if end_sq == 100:
        return None, lines, dict(winner=slot, text="Reached 100")
    if roll == 6:
        lines.append(f"{who} rolled a six and goes again.")
    else:
        state["turn"] = "p2" if slot == "p1" else "p1"
    return None, lines, None


def bot_move(state, slot):
    return {"action": "roll"}


def view_state(state, viewer):
    return dict(pos=state["pos"], turn=state["turn"], last=state["last"], n=state["n"])
