# Security

## Reporting a problem

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting (the "Report a vulnerability" button on the Security tab), or message [@shade_ofc](https://x.com/shade_ofc) on X. You will get a reply as soon as possible.

## How the project handles secrets and players

- **Database credentials stay on the server.** They are read from `.env` (which is in `.gitignore`) and are used only by `store.py`. The browser never sees them, and the server never returns them.
- **No accounts.** A player is a random token that the server issued for one room or clan and that their browser keeps. Tokens are compared in constant time and are never included in what is sent to other players.
- **Room passwords** are stored as salted PBKDF2-SHA256 hashes, never in clear text.
- **The server is the referee.** Moves are validated server-side. Hidden information (a pending move, an opponent's fighter pick) is never sent to the other player until it is revealed.
- **Input is bounded.** Names, room names and chat are length limited and stripped of control characters, chat is rate limited, and the front end escapes everything it renders.

## If you published your credentials by accident

Delete that cluster in the shadeDB dashboard and create a new one, then update `.env`. Treat any token that has been in a git history, a screenshot or a chat as public.

## Running it in public

Run one server process per database (rooms are locked per process), put it behind HTTPS, and keep `.env` out of the image and the repository. The provided `Dockerfile` does this.
