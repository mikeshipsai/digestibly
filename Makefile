COMPOSE = docker compose -f docker/docker-compose.yml

UV_BIN := $(shell command -v uv 2>/dev/null)
ifeq ($(UV_BIN),)
  UV_BIN := $(HOME)/.local/bin/uv
endif
UV = $(UV_BIN) run

.PHONY: help install sync up down restart build logs ps init-auth clean-db reset-db login bot run-digest

help:
	@echo "  make install    - uv sync"
	@echo "  make login      - Telethon auth (once)"
	@echo "  make bot        - run bot locally"
	@echo "  make run-digest - full pipeline, no Telegram send"
	@echo "  make up/down    - Docker compose"
	@echo "  make clean-db   - reset SQLite"

install sync:
	@test -x "$(UV_BIN)" || (echo "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)
	$(UV_BIN) sync

login:
	$(UV) python -m scripts.telethon_login

bot:
	$(UV) python -m app.main

run-digest:
	$(UV) python -m scripts.run_digest --no-send

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down && $(COMPOSE) up -d --build

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
	./scripts/clean_db.sh && $(COMPOSE) down && $(COMPOSE) up -d --build
