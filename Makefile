COMPOSE = docker compose -f docker/docker-compose.yml

# uv may be installed via install.sh into ~/.local/bin (not always in PATH)
UV_BIN := $(shell command -v uv 2>/dev/null)
ifeq ($(UV_BIN),)
  UV_BIN := $(HOME)/.local/bin/uv
endif
UV = $(UV_BIN) run

.PHONY: help install sync up down restart build logs ps init-auth clean-db reset-db export-channels recluster-channels test-collect run-digest preview-clusters login bot

help:
	@echo "Available commands:"
	@echo "  make install    - uv sync (create .venv + install deps)"
	@echo "  make up         - build and start services"
	@echo "  make down       - stop and remove services"
	@echo "  make restart    - restart services"
	@echo "  make build      - rebuild bot image"
	@echo "  make logs       - show recent logs"
	@echo "  make ps         - show service status"
	@echo "  make init-auth  - one-time Telegram auth flow (profile init)"
	@echo "  make clean-db   - reset SQLite database file"
	@echo "  make reset-db   - clean DB and restart services"
	@echo "  make login      - Telethon auth (local)"
	@echo "  make bot        - run bot + scheduler"
	@echo "  make export-channels    - export all channels to data/channels.csv"
	@echo "  make recluster-channels - re-apply themes to channels.csv (no API)"
	@echo "  make test-collect       - collect yesterday's posts + token estimate"
	@echo "  make run-digest         - full pipeline, no Telegram send"
	@echo "  make preview-clusters   - show cluster stats from channels.csv"

install sync:
	@test -x "$(UV_BIN)" || (echo "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)
	$(UV_BIN) sync

login:
	$(UV) python -m scripts.telethon_login

bot:
	$(UV) python -m app.main

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down
	$(COMPOSE) up -d --build

build:
	$(COMPOSE) build

logs:
	$(COMPOSE) logs --tail=200

ps:
	$(COMPOSE) ps

init-auth:
	$(COMPOSE) --profile init run --rm init

clean-db:
	./scripts/clean_db.sh

reset-db:
	./scripts/clean_db.sh
	$(COMPOSE) down
	$(COMPOSE) up -d --build

export-channels:
	$(UV) python -m scripts.export_channels

recluster-channels:
	$(UV) python -m scripts.recluster_channels

test-collect:
	$(UV) python -m scripts.test_collect

run-digest:
	$(UV) python -m scripts.run_digest --no-send

preview-clusters:
	$(UV) python -m scripts.preview_clusters
