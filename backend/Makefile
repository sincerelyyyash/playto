.PHONY: help up down build logs migrate makemigrations seed shell test lint format clean tokens

help:
	@echo "Targets:"
	@echo "  build           Build images"
	@echo "  up              Start postgres, redis, web, worker, beat"
	@echo "  down            Stop containers"
	@echo "  logs            Tail logs"
	@echo "  migrate         Run migrations"
	@echo "  makemigrations  Create migrations"
	@echo "  seed            Seed demo merchants + credit history (prints API tokens)"
	@echo "  tokens          Print API tokens for seeded merchants"
	@echo "  shell           Open Django shell"
	@echo "  test            Run pytest"
	@echo "  lint            Run ruff check"
	@echo "  format          Run ruff format"
	@echo "  clean           Down + remove volumes"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm web python manage.py migrate

makemigrations:
	docker compose run --rm web python manage.py makemigrations

seed:
	docker compose run --rm web python manage.py seed_demo

tokens:
	docker compose run --rm web python manage.py print_tokens

shell:
	docker compose run --rm web python manage.py shell

test:
	docker compose run --rm web pytest -xvs

lint:
	docker compose run --rm web ruff check .

format:
	docker compose run --rm web ruff format .

clean:
	docker compose down -v
