.PHONY: setup sim test eval lowmem clean

PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

# On Windows (without WSL), use .venv\Scripts\python.exe
ifeq ($(OS),Windows_NT)
	PIP := $(VENV)/Scripts/pip.exe
	PY := $(VENV)/Scripts/python.exe
endif

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

sim:
	@echo "=== Generating 28-day synthetic history (seed=42) ==="
	$(PY) -m sim.generator --days 28 --seed 42 --out data/vehicle.db
	@echo "=== Done ==="

test:
	$(PY) -m pytest tests/ -v --tb=short

eval:
	$(PY) eval/run_eval.py --split all

eval-planner:
	$(PY) eval/eval_planner_300.py

eval-e2e:
	$(PY) eval/eval_e2e.py

download-model:
	$(PY) scripts/download_model.py

lowmem:
	docker compose up --build

clean:
	rm -f data/vehicle.db
	rm -f data/candump/*.log
	rm -f eval/ground_truth.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
