"""Chess: a compact, complete rules engine (no dependencies) plus room glue.

Positions are stored as FEN strings. The server owns all rules: it sends each
player the legal moves, so the browser needs no chess logic at all.
Covered: castling, en passant, promotion, check, checkmate, stalemate,
fifty-move rule, threefold repetition and insufficient material.
"""
import hashlib
import random
import re

TITLE = "Chess"
BLURB = "The classic. Full rules, a casual computer opponent, and a move list."
FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KNIGHT = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
KING = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
BISHOP = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ROOK = [(-1, 0), (1, 0), (0, -1), (0, 1)]
VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE, INF = 100000, 10 ** 9
SQ = re.compile(r"^[a-h][1-8]$")


def sq_name(i):
    return FILES[i % 8] + str(8 - i // 8)


def sq_index(s):
    return (8 - int(s[1])) * 8 + FILES.index(s[0])


# ------------------------------------------------------------------ position
def parse(fen):
    f = fen.split()
    board = []
    for ch in f[0]:
        if ch == "/":
            continue
        board += ["."] * int(ch) if ch.isdigit() else [ch]
    return dict(b=board, side=f[1], castle="" if f[2] == "-" else f[2],
                ep=-1 if f[3] == "-" else sq_index(f[3]), half=int(f[4]), full=int(f[5]))


def to_fen(pos):
    rows = []
    for r in range(8):
        row, empty = "", 0
        for p in pos["b"][r * 8:r * 8 + 8]:
            if p == ".":
                empty += 1
            else:
                row += (str(empty) if empty else "") + p
                empty = 0
        rows.append(row + (str(empty) if empty else ""))
    return " ".join(["/".join(rows), pos["side"], pos["castle"] or "-",
                     sq_name(pos["ep"]) if pos["ep"] >= 0 else "-", str(pos["half"]), str(pos["full"])])


def attacked(b, sq, by):
    """Is square `sq` attacked by side `by` ('w' or 'b')?"""
    r, c = divmod(sq, 8)
    w = by == "w"
    pr = r + 1 if w else r - 1
    if 0 <= pr < 8:
        for dc in (-1, 1):
            if 0 <= c + dc < 8 and b[pr * 8 + c + dc] == ("P" if w else "p"):
                return True
    for steps, piece in ((KNIGHT, "N"), (KING, "K")):
        piece = piece if w else piece.lower()
        for dr, dc in steps:
            rr, cc = r + dr, c + dc
            if 0 <= rr < 8 and 0 <= cc < 8 and b[rr * 8 + cc] == piece:
                return True
    for dirs, pieces in ((BISHOP, "BQ"), (ROOK, "RQ")):
        pieces = pieces if w else pieces.lower()
        for dr, dc in dirs:
            rr, cc = r + dr, c + dc
            while 0 <= rr < 8 and 0 <= cc < 8:
                p = b[rr * 8 + cc]
                if p != ".":
                    if p in pieces:
                        return True
                    break
                rr, cc = rr + dr, cc + dc
    return False


def _add_pawn(out, f, t, promo, kind):
    if promo:
        out.extend((f, t, q, kind) for q in "qrbn")
    else:
        out.append((f, t, "", kind))


def pseudo(pos):
    b, white = pos["b"], pos["side"] == "w"
    out = []
    for i, p in enumerate(b):
        if p == "." or p.isupper() != white:
            continue
        r, c = divmod(i, 8)
        k = p.upper()
        if k == "P":
            dr, start, last = (-1, 6, 0) if white else (1, 1, 7)
            nr = r + dr
            if 0 <= nr < 8:
                t = nr * 8 + c
                if b[t] == ".":
                    _add_pawn(out, i, t, nr == last, "")
                    if r == start and b[t + dr * 8] == ".":
                        out.append((i, t + dr * 8, "", "dbl"))
                for dc in (-1, 1):
                    if 0 <= c + dc < 8:
                        t = nr * 8 + c + dc
                        if b[t] != "." and b[t].isupper() != white:
                            _add_pawn(out, i, t, nr == last, "")
                        elif b[t] == "." and t == pos["ep"]:
                            out.append((i, t, "", "ep"))
        elif k in "NK":
            for dr, dc in (KNIGHT if k == "N" else KING):
                rr, cc = r + dr, c + dc
                if 0 <= rr < 8 and 0 <= cc < 8:
                    t = rr * 8 + cc
                    if b[t] == "." or b[t].isupper() != white:
                        out.append((i, t, "", ""))
        else:
            for dr, dc in (BISHOP if k == "B" else ROOK if k == "R" else BISHOP + ROOK):
                rr, cc = r + dr, c + dc
                while 0 <= rr < 8 and 0 <= cc < 8:
                    t = rr * 8 + cc
                    if b[t] == ".":
                        out.append((i, t, "", ""))
                    else:
                        if b[t].isupper() != white:
                            out.append((i, t, "", ""))
                        break
                    rr, cc = rr + dr, cc + dc
    enemy = "b" if white else "w"
    base, king, rook = (60, "K", "R") if white else (4, "k", "r")
    if b[base] == king and not attacked(b, base, enemy):
        if king in pos["castle"] and b[base + 1] == b[base + 2] == "." and b[base + 3] == rook \
                and not attacked(b, base + 1, enemy) and not attacked(b, base + 2, enemy):
            out.append((base, base + 2, "", "K"))
        q = "Q" if white else "q"
        if q in pos["castle"] and b[base - 1] == b[base - 2] == b[base - 3] == "." and b[base - 4] == rook \
                and not attacked(b, base - 1, enemy) and not attacked(b, base - 2, enemy):
            out.append((base, base - 2, "", "Q"))
    return out


def make(pos, m):
    f, t, promo, kind = m
    b = pos["b"][:]
    piece, cap = b[f], b[t]
    white = pos["side"] == "w"
    b[t], b[f] = piece, "."
    if kind == "ep":
        b[t + 8 if white else t - 8] = "."
    if promo:
        b[t] = promo.upper() if white else promo.lower()
    if kind == "K":
        b[f + 1], b[f + 3] = b[f + 3], "."
    elif kind == "Q":
        b[f - 1], b[f - 4] = b[f - 4], "."
    castle = pos["castle"]
    if piece == "K":
        castle = castle.replace("K", "").replace("Q", "")
    elif piece == "k":
        castle = castle.replace("k", "").replace("q", "")
    for sq, right in ((63, "K"), (56, "Q"), (7, "k"), (0, "q")):
        if f == sq or t == sq:
            castle = castle.replace(right, "")
    return dict(b=b, side="b" if white else "w", castle=castle, ep=(f + t) // 2 if kind == "dbl" else -1,
                half=0 if piece.upper() == "P" or cap != "." else pos["half"] + 1,
                full=pos["full"] + (0 if white else 1))


def in_check(pos):
    me = pos["side"]
    return attacked(pos["b"], pos["b"].index("K" if me == "w" else "k"), "b" if me == "w" else "w")


def legal(pos):
    me, opp = pos["side"], "b" if pos["side"] == "w" else "w"
    king = "K" if me == "w" else "k"
    out = []
    for m in pseudo(pos):
        n = make(pos, m)
        if not attacked(n["b"], n["b"].index(king), opp):
            out.append(m)
    return out


def san(pos, m, legal_moves):
    f, t, promo, kind = m
    piece = pos["b"][f].upper()
    if kind in ("K", "Q"):
        s = "O-O" if kind == "K" else "O-O-O"
    else:
        cap = pos["b"][t] != "." or kind == "ep"
        if piece == "P":
            s = (FILES[f % 8] + "x" if cap else "") + sq_name(t) + ("=" + promo.upper() if promo else "")
        else:
            others = [x for x in legal_moves if x[:2] != (f, t) and pos["b"][x[0]].upper() == piece and x[1] == t]
            dis = ""
            if others:
                if all(x[0] % 8 != f % 8 for x in others):
                    dis = FILES[f % 8]
                elif all(x[0] // 8 != f // 8 for x in others):
                    dis = str(8 - f // 8)
                else:
                    dis = sq_name(f)
            s = piece + dis + ("x" if cap else "") + sq_name(t)
    n = make(pos, m)
    if in_check(n):
        s += "#" if not legal(n) else "+"
    return s


def insufficient(pos):
    rest = [(i, p.upper()) for i, p in enumerate(pos["b"]) if p not in ".Kk"]
    if not rest:
        return True
    if len(rest) == 1:
        return rest[0][1] in "NB"
    if all(p == "B" for _, p in rest):
        return len({(i // 8 + i % 8) % 2 for i, _ in rest}) == 1
    return False


def rep_key(pos):
    return hashlib.md5(" ".join(to_fen(pos).split()[:4]).encode()).hexdigest()[:8]


def outcome(pos, reps):
    """Why the game is over, or None."""
    if not legal(pos):
        return "Checkmate" if in_check(pos) else "Stalemate"
    if insufficient(pos):
        return "Insufficient material"
    if pos["half"] >= 100:
        return "Fifty-move rule"
    if reps >= 3:
        return "Threefold repetition"
    return None


# ------------------------------------------------------------------- the bot
def evaluate(pos):
    s = 0
    for i, p in enumerate(pos["b"]):
        if p == ".":
            continue
        k, r, c = p.upper(), i // 8, i % 8
        v = VALUES[k]
        if k in "PNBQ":
            v += int(10 - 3 * max(abs(r - 3.5), abs(c - 3.5)))
        if k == "P":
            v += (6 - r) * 4 if p.isupper() else (r - 1) * 4
        s += v if p.isupper() else -v
    return s if pos["side"] == "w" else -s


def _order(pos):
    b = pos["b"]
    return lambda m: -(VALUES[b[m[1]].upper()] if b[m[1]] != "." else 0) - (50 if m[2] else 0)


def search(pos, depth, a, b):
    moves = legal(pos)
    if not moves:
        return -(MATE + depth) if in_check(pos) else 0
    if depth == 0:
        return evaluate(pos)
    best = -INF
    for m in sorted(moves, key=_order(pos)):
        s = -search(make(pos, m), depth - 1, -b, -a)
        best = max(best, s)
        a = max(a, s)
        if a >= b:
            break
    return best


def bot_move(state, slot):
    """A casual opponent: looks two moves ahead (three in endgames), varies a little."""
    pos = parse(state["fen"])
    depth = 3 if sum(p != "." for p in pos["b"]) <= 10 else 2
    scored = [(-search(make(pos, m), depth - 1, -INF, INF), m) for m in sorted(legal(pos), key=_order(pos))]
    best = max(s for s, _ in scored)
    m = random.choice([m for s, m in scored if s >= best - 8])
    return dict(**{"from": sq_name(m[0])}, to=sq_name(m[1]), promo=m[2])


# ----------------------------------------------------------------- room glue
def new_state(first="p1"):
    pos = parse(START_FEN)
    return dict(fen=START_FEN, white=first, turn=first, moves=[], last=None, draw_offer=None,
                reps={rep_key(pos): 1})


def apply(state, slot, move, names):
    """Returns (error, log_lines, end). Never mutates state when it returns an error."""
    if state["turn"] != slot:
        return "It is not your turn.", [], None
    f, t = str(move.get("from", "")), str(move.get("to", ""))
    if not (SQ.match(f) and SQ.match(t)):
        return "Illegal move.", [], None
    pos = parse(state["fen"])
    legal_moves = legal(pos)
    cands = [m for m in legal_moves if m[0] == sq_index(f) and m[1] == sq_index(t)]
    if not cands:
        return "Illegal move.", [], None
    promo = str(move.get("promo") or "q").lower()
    m = next((c for c in cands if c[2] == promo), cands[0]) if len(cands) > 1 else cands[0]
    state["moves"].append(san(pos, m, legal_moves))
    pos = make(pos, m)
    state["fen"], state["last"], state["draw_offer"] = to_fen(pos), [f, t], None
    key = rep_key(pos)
    state["reps"][key] = state["reps"].get(key, 0) + 1
    state["turn"] = "p2" if slot == "p1" else "p1"
    why = outcome(pos, state["reps"][key])
    if why:
        return None, [], dict(winner=slot if why == "Checkmate" else "draw", text=why)
    return None, [], None


def offer_draw(state, slot, names):
    if state.get("draw_offer") and state["draw_offer"] != slot:
        return None, ["Draw agreed."], dict(winner="draw", text="Draw by agreement")
    state["draw_offer"] = slot
    return None, [f"{names[slot]} offers a draw."], None


def view_state(state, viewer):
    pos = parse(state["fen"])
    moves = {}
    if state["turn"] == viewer:
        for m in legal(pos):
            moves.setdefault(sq_name(m[0]), [])
            if sq_name(m[1]) not in moves[sq_name(m[0])]:
                moves[sq_name(m[0])].append(sq_name(m[1]))
    check = sq_name(pos["b"].index("K" if pos["side"] == "w" else "k")) if in_check(pos) else None
    return dict(fen=state["fen"], white=state["white"], turn=state["turn"], last=state["last"],
                moves=state["moves"], legal=moves, check=check, draw_offer=state["draw_offer"])
