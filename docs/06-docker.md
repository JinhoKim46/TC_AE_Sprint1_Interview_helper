# Running Interview Helper in Docker

Docker runs the app as a long-lived local service: it starts in the background, restarts after a crash or a reboot (`restart: unless-stopped`), and keeps your data in the project's `data/` folder on the host. For development, `uv run streamlit run app/main.py` is still the quicker loop.

The setup is three files at the repo root: `Dockerfile` (the image), `compose.yaml` (how it runs) and `.dockerignore` (what may go into the image). A `Makefile` adds short aliases.

## Prerequisites

- Docker Engine with the Compose v2 plugin (`docker compose version` should print a version). Tested with Docker 29.
- An OpenRouter API key (https://openrouter.ai/keys).
- A clone of this repo. Nothing else: Python and all dependencies live inside the image.

## First run

1. Create your settings file: `cp .env.example .env`, then set `OPENROUTER_API_KEY` (and `APP_SECRET_KEY` if you use the TOTP login). Any other setting from `src/interview_app/config.py` can go here too, e.g. `MODELS__INTERVIEWER=...`.
2. Check your user id: `id -u` and `id -g`. If both print `1000` (the usual case on a single-user Linux machine) there is nothing to do. Otherwise add `APP_UID=<your uid>` and `APP_GID=<your gid>` to `.env` (see "Permission denied on data/" below for why).
3. Start it: `make up` (it creates `data/` first; by hand that is `mkdir -p data && docker compose up -d --build`). The first build downloads the base image and the dependencies and takes a minute or two; later builds reuse the cached layers.
4. Wait until it is healthy: `make status` shows `(healthy)` after about 10 to 20 seconds.
5. Open http://localhost:8501.

## Everyday commands (Makefile)

Everything is wrapped in a `Makefile` at the repo root, so you never have to type a `docker` command. Run `make` (or `make help`) to list the targets. Each one is a thin wrapper, so the equivalent `docker compose` command is shown too.

Docker service:

- `make up`: build the image if anything changed (cached layers make this quick) and start the app in the background. Stops with a clear message if `.env` is missing. Same as `docker compose up -d --build`.
- `make status` (or `make ps`): container state, health (`healthy` / `starting` / `unhealthy`) and the published port. Same as `docker compose ps`.
- `make logs`: follow the app logs, Ctrl-C to stop. Same as `docker compose logs -f --tail=100`.
- `make url` (or `make open`): print http://localhost:8501.
- `make restart`: restart the running container. It does not pick up code or `.env` changes (use `make up` for those). Same as `docker compose restart`.
- `make down`: stop and remove the container. Your data in `data/` and the built image stay. Same as `docker compose down`.
- `make rebuild`: rebuild the image from scratch without the build cache, then start. Use it when something looks stale or broken; for a normal update `make up` is enough.
- `make shell`: open a shell inside the running container (as the unprivileged `app` user). Same as `docker compose exec app sh`.
- `make backup`: copy `data/app.db` to `data/backups/app-<timestamp>.db`. Uses SQLite's backup API (via the host's `python3`), so the copy is consistent even while the app is running.
- `make clean`: stop the app and remove its image. It never touches `data/`. Same as `docker compose down --rmi all`.

Development without Docker:

- `make run`: run the app directly with uv (`uv run streamlit run app/main.py`).
- `make test`: unit tests without network, as in CI (`uv run pytest -m "not live"`).
- `make lint`: ruff lint and format check, as in CI.
- `make fmt`: format the code and apply ruff's automatic fixes.

Don't run `make run` and `make up` at the same time: both want port 8501.

## Updating after `git pull`

The code is copied into the image at build time, so a pull alone changes nothing in the running app. Rebuild and restart in one step: `make up` (that is `docker compose up -d --build`). Only the layers after the change are rebuilt: a code-only change takes seconds, a change to `pyproject.toml` or `uv.lock` reinstalls the dependencies.

Changes to `.env` need the container to be recreated with the new environment: `make up` does that (Compose notices the changed env file). `make restart` keeps the old environment.

## Where the data lives

Everything the app writes goes to `/app/data` inside the container, which is a bind mount of `./data` in the repo folder on the host: the SQLite database `data/app.db`, the model-price cache `data/cache/` and any uploads. Because it is on the host, it survives `restart`, `down`, `up --build` and deleting the image. The same folder is used when you run the app with `uv run`, so both ways see the same interviews.

To back up the database, run `make backup`: it writes a consistent copy to `data/backups/app-<timestamp>.db`, even while the app is running. To back up the whole folder (database, cache, uploads), stop the app first and archive it: `make down && tar czf interview-helper-data-$(date +%F).tar.gz data/ && make up`.

To restore, `make down`, copy the backup over `data/app.db` (or unpack the archive into `data/`) and `make up`. The backup holds your real CVs and interview answers, so keep it somewhere private.

## What is (and is not) in the image

`.dockerignore` is an allow-list: only `pyproject.toml`, `uv.lock`, `app/`, `src/`, `samples/` and the two docs files the app reads (`docs/rubric.json`, `docs/01-interviewer-guideline.md`) are sent to the build. Your `.env`, `data/`, `docs/applications/`, `references/` and `.git` never reach the image, so the image is safe to keep or rebuild without leaking the API key or personal documents. The key reaches the app only at runtime, through `env_file: .env` in `compose.yaml`.

The app runs as an unprivileged user `app`, not root. The project is installed in editable mode from `/app/src`, so `PROJECT_ROOT` in `config.py` resolves to `/app` exactly as it does in a checkout.

## Why the port is bound to localhost

`compose.yaml` publishes `127.0.0.1:8501:8501`, not `8501:8501`. The app has no login of its own and spends money on your OpenRouter key, so it must only be reachable from this machine. A bare `8501:8501` would listen on every network interface, and Docker's port rules bypass most host firewalls (ufw included), so anyone on the same Wi-Fi could use it. If you ever need it from another device, put it behind something with authentication (an SSH tunnel is the simplest: `ssh -L 8501:localhost:8501 <this machine>`) rather than widening the binding.

## Troubleshooting

**Permission denied on data/ (`unable to open database file`, `PermissionError`).** A bind mount keeps the host's ownership, and the container user can only write where its UID is allowed to. The image creates its user with UID/GID 1000 by default. Check `ls -ln data` and `id -u`: if the numbers differ, set `APP_UID` and `APP_GID` in `.env` and run `make up`. If `data/` is owned by root, Docker created it because it was missing when you first started; fix it with `sudo chown -R $(id -u):$(id -g) data` (`make up` runs `mkdir -p data` first to avoid this).

**Port 8501 already in use (`bind: address already in use`).** Something else listens on 8501, often a `make run` / `uv run streamlit` session you left open. Stop it, or find it with `ss -ltnp | grep 8501`. To use another port, change the left side of the mapping in `compose.yaml`, e.g. `"127.0.0.1:8502:8501"`, and open http://localhost:8502.

**Container is `unhealthy` or keeps restarting.** Check `make status`, then read the logs with `make logs`. The healthcheck asks Streamlit for `http://localhost:8501/_stcore/health` every 30 seconds and expects `ok`; you can run the same check by hand from the host with `curl -s localhost:8501/_stcore/health`. A missing `.env` stops `make up` with a message telling you to `cp .env.example .env` (plain Compose fails with `env file .env not found`).

**The app shows an API error on the first interview.** The key in `.env` is missing or wrong, or the container was started before you set it. Fix `.env`, then `make up` to recreate the container with the new value.

**The change I pulled does not show up.** You restarted instead of rebuilding. Run `make up`.

**The logs print a "Network URL" and an "External URL".** Streamlit prints the addresses it would have inside an unrestricted network. They don't apply here: the port is published on 127.0.0.1 only, so http://localhost:8501 is the only way in.
