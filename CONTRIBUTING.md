# Contributing to Heaven Duels

Thanks for helping. This is a small project with one big rule: **shadeDB is the only channel between players.** No websockets, no server-sent events, no message broker. A feature earns its place by working through reads and writes to the database.

## Getting set up

```bash
git clone <your-fork-url> heaven-duels && cd heaven-duels
./start.sh --offline        # local storage, no account needed
python -m unittest discover -s tests
```

The tests need no network and no credentials. They use a fake shadeDB endpoint (`tests/fake_shadedb.py`) built from the public docs at https://shadedb.duckdns.org/llms.

`./start.sh` (no flag) uses the shared demo database, which is public: fine for trying things, not for anything private. If you have your own shadeDB instance, copy `.env.example` to `.env`, fill it in, run `python scripts/check_db.py`, and start with `./start.sh --custom`. **Never commit your own `.env`.**

## What a good pull request looks like

- It does one thing, and the tests pass (`python -m unittest discover -s tests`).
- New behaviour comes with a test. Rules for a game belong in a unit test, and anything a player could cheat on belongs in a test that checks what the server sends them.
- The server stays the referee. Browsers never decide whether a move is legal, and the server never sends a player information they should not have (a pending move, the opponent's pick, a token).
- The interface stays black and white and flat: no gradients, no glows, no new colours. It has to work from a 360 pixel phone to a wide monitor, in light and dark.
- No new runtime dependency unless there is a very good reason. Today it is Flask and python-dotenv.

## Adding a game

A game is one file in `games/` and one line in `games/__init__.py`. Real-time games also send small updates through `realtime.py`, which writes one record per player and reads the other's. It provides `TITLE`, `BLURB`, `new_state`, `apply`, `bot_move` and `view_state`, plus `can_act` if both players move at once. The README has the details. You also need a front-end view in `static/index.html`. Rooms, chat, passwords, rematches, clans and storage come for free.

## Reporting bugs and ideas

Use the issue templates. For security problems, see [SECURITY.md](SECURITY.md) and please do not open a public issue.

## Say hello

Follow along or tell the author what you built: [@shade_ofc](https://x.com/shade_ofc) on X.
