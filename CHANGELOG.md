# Changelog

## 1.0.0

First public release.

- Three games for two players: **chess** (full rules and a casual computer opponent), **Snakes & Ladders**, and **Heaven Fighters**, a simultaneous-move duel with four fighters.
- **Rooms** with names and optional passwords. The host chooses whether leaving deletes the room.
- **Clans**: a named group with a unique cable ID, a member list that remembers who joined and left, a chat, and game invites.
- **Speed test** that times real shadeDB queries and says whether lag comes from the database or the network.
- shadeDB is the only channel between players: no websockets, no server-sent events. Persistent HTTPS connections to the database.
- Black and white interface, light and dark, full screen on phones, installable as an app, chat with reactions.
- Offline mode with a local file, LAN play, Docker image, and a test suite that needs no network.
