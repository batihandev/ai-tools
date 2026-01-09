VENV_DIR := .venv
PYTHON   := /usr/bin/python3
PIP      := $(VENV_DIR)/bin/pip
API_HOST ?= 127.0.0.1
API_PORT ?= 8008
UVICORN  := $(VENV_DIR)/bin/uvicorn
FRONTEND_DIR := frontend
NPM          := npm
.PHONY: venv install wrappers clean-venv server server-open frontend-install frontend-dev dev

venv:
	@echo "Creating venv..."
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	@echo "Installing deps..."
	$(PIP) install -r requirements.txt
	@$(MAKE) wrappers

wrappers:
	@echo "Generating wrappers..."
	@chmod +x ./generate_wrappers.sh
	@./generate_wrappers.sh

clean-venv:
	rm -rf $(VENV_DIR)

server: install
	@echo "Starting FastAPI on http://$(API_HOST):$(API_PORT)/"
	@$(UVICORN) server.app.main:app --host $(API_HOST) --port $(API_PORT) --reload

frontend-install:
	@cd $(FRONTEND_DIR) && $(NPM) install

frontend-dev: frontend-install
	@cd $(FRONTEND_DIR) && $(NPM) run dev -- --host 127.0.0.1 --port 5173