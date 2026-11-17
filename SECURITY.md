# Security

## Reporting a problem

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting (the "Report a vulnerability" button on the Security tab), or message [@shade_ofc](https://x.com/shade_ofc) on X. You will get a reply as soon as possible.

## How the project handles secrets and players

- **Database credentials stay on the server.** They are read from `.env` (which is in `.gitignore`) and are used only by `store.py`. The browser never sees them, and the server never returns them.
- **The demo database is public by design.** `start.sh` contains credentials for a shared demo database and writes them to `.env` so the game works straight after cloning. Anyone with the repository can read, change and delete data in it, so treat everything in it as public and never store anything private there. The maintainer should use a dedicated, disposable token limited to one partition, and rotate it if it is abused. Use `./start.sh --custom` with your own `.env` for anything private.
- **No accounts.** A player is a random token that the server issued for one room or clan and that their browser keeps. Tokens are compared in constant time and are never included in what is sent to other players.
- **Room passwords** are stored as salted PBKDF2-SHA256 hashes, never in clear text.
- **The server is the referee.** Moves are validated server-side. Hidden information (a pending move, an opponent's fighter pick) is never sent to the other player until it is revealed.
- **Heaven Brawl is friendly, not tamper-proof.** Each device simulates its own fighter and reports hits, so a modified client could cheat. Matches are not ranked and nothing is staked on them. Its updates are validated for size and for who is sending, and never carry anything but game state.
- **Input is bounded.** Names, room names and chat are length limited and stripped of control characters, chat is rate limited, and the front end escapes everything it renders.

## If you published credentials you did not mean to

The demo credentials in `start.sh` are intentional. Any other token (yours, in your own `.env`) that has been in a git history, a screenshot or a chat should be treated as public: delete that cluster in the shadeDB dashboard, create a new one, and update `.env`.

## Running it in public

Run one server process per database (rooms are locked per process), put it behind HTTPS, and keep your own `.env` out of the image and the repository. The provided `Dockerfile` does this, and `docker-compose.yml` reads `.env` at run time.
