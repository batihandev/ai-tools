VENV_DIR := .venv
PYTHON   := /usr/bin/python3
PIP      := $(VENV_DIR)/bin/pip

.PHONY: venv install wrappers clean-venv

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
