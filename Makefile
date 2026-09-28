# JAAL — Makefile for one-command runs
# Usage: make dev   (starts both backend + frontend)

.PHONY: dev backend frontend test build install

## Start both backend and frontend (dev mode)
dev:
	@echo "Starting JAAL (backend + frontend)..."
	@$(MAKE) -j2 backend frontend

## Start backend only
backend:
	uvicorn backend.main:app --reload --port 8000

## Start frontend only
frontend:
	cd frontend && npm run dev

## Run all Python tests
test:
	python -m pytest tests/ -v

## Build frontend for production
build:
	cd frontend && npm run build

## Install Python and JS dependencies
install:
	pip install -r requirements.txt
	cd frontend && npm install

## Run a quick smoke test (offline, no Bob key needed)
smoke:
	FORCE_FALLBACK=1 BOB_API_KEY=test python scripts/smoke_extraction.py
