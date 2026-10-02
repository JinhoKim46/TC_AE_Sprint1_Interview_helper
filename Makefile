# Interview Helper: one place for the everyday commands. Run `make` to list them.
# Docker targets wrap `docker compose` (see docs/06-docker.md); dev targets run the app with uv directly.

URL     := http://localhost:8501
STAMP   := $(shell date +%Y%m%d-%H%M%S)

.DEFAULT_GOAL := help
.PHONY: help up down restart rebuild logs ps status shell open url backup clean run test lint fmt \
	check-env data-dir

help: ## Show this list
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# --- Docker service -----------------------------------------------------------------------------

up: check-env data-dir ## Build if needed and start the app in the background
	docker compose up -d --build
	@echo "Starting: $(URL) (run 'make status' to see when it is healthy)"

down: ## Stop and remove the container (data/ and the image stay)
	docker compose down

restart: ## Restart the running container (picks up no code or .env changes)
	docker compose restart

rebuild: check-env data-dir ## Rebuild the image from scratch (no cache) and start
	docker compose build --no-cache
	docker compose up -d

logs: ## Follow the app logs (Ctrl-C to stop)
	docker compose logs -f --tail=100

ps: status ## Alias of status
status: ## Show the container state and health
	@docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'

shell: ## Open a shell inside the running container
	docker compose exec app sh

open: url ## Alias of url
url: ## Print the app URL
	@echo $(URL)

backup: ## Copy data/app.db to data/backups/app-<timestamp>.db
	@test -f data/app.db || { echo "No data/app.db yet: nothing to back up."; exit 1; }
	@mkdir -p data/backups
	@# sqlite3's backup API gives a consistent copy even while the app is writing (a plain cp may not).
	@python3 -c "import sqlite3; s = sqlite3.connect('data/app.db'); d = sqlite3.connect('data/backups/app-$(STAMP).db'); s.backup(d); d.close(); s.close()"
	@echo "Saved data/backups/app-$(STAMP).db"

clean: ## Stop the app and remove its image (never touches data/)
	@# --rmi all removes the service images (interview-helper:local); bind-mounted data/ is never removed.
	docker compose down --rmi all

# --- Development without Docker -----------------------------------------------------------------

run: ## Run the app locally with uv (no Docker)
	uv run streamlit run app/main.py

test: ## Unit tests (no network), as in CI
	uv run pytest -m "not live"

lint: ## Ruff lint and format check, as in CI
	uv run ruff check
	uv run ruff format --check

fmt: ## Format and auto-fix with ruff
	uv run ruff format
	uv run ruff check --fix

# --- Helpers ------------------------------------------------------------------------------------

check-env:
	@test -f .env || { echo "No .env file. Create it first:  cp .env.example .env  (then set OPENROUTER_API_KEY)"; exit 1; }

# If ./data is missing, Docker creates it owned by root and the app (non-root) can't write its DB.
data-dir:
	@mkdir -p data
