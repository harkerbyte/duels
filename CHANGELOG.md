# Changelog

## 1.1.0

- **Heaven Brawl**: a real-time arcade fighter over shadeDB. Each player writes their own record and reads the other's. It checks your connection first and lets each player decide whether to play, has on-screen touch controls plus keyboard, a wide mode, and a practice mode against the computer that needs no network.
- **Heaven Fighters** (the turn-based duel), **clans** with cable IDs and chat, a **speed test** that says whether lag is the database or the network, and leave-and-delete for rooms.
- Persistent connections to shadeDB.

- `start.sh` writes a ready-made `.env` for a shared demo database on first run, so the game works straight after cloning. `./start.sh --custom` uses your own `.env` and never touches it. `--demo` and `--write-env` regenerate the demo one. A `.env` of your own is never overwritten.
- The game says when you are on the demo database, because rooms and chat there are public.

## 1.0.0

First public release.

- Three games for two players: **chess** (full rules and a casual computer opponent), **Snakes & Ladders**, and **Heaven Fighters**, a simultaneous-move duel with four fighters.
- **Rooms** with names and optional passwords. The host chooses whether leaving deletes the room.
- **Clans**: a named group with a unique cable ID, a member list that remembers who joined and left, a chat, and game invites.
- **Speed test** that times real shadeDB queries and says whether lag comes from the database or the network.
- shadeDB is the only channel between players: no websockets, no server-sent events. Persistent HTTPS connections to the database.
- Black and white interface, light and dark, full screen on phones, installable as an app, chat with reactions.
- Offline mode with a local file, LAN play, Docker image, and a test suite that needs no network.
