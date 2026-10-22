.PHONY: setup sim test eval eval-planner eval-e2e download-model lowmem lowmem-build lowmem-check lowmem-test lowmem-eval lowmem-profile clean

PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
DOCKER_IMAGE ?= vehiclegpt:latest

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
	$(PY) -m pytest tests/ -m "not slow" -v --tb=short

test-all:
	$(PY) -m pytest tests/ -v --tb=short

eval:
	$(PY) eval/run_eval.py --split all

eval-planner:
	$(PY) eval/eval_planner_300.py

eval-e2e:
	$(PY) eval/eval_e2e.py

download-model:
	$(PY) scripts/download_model.py

# ── Milestone 4 Capped Container Targets (--memory=2g --memory-swap=2g --cpus=2 --network none) ──
lowmem-build:
	docker build -t $(DOCKER_IMAGE) .

lowmem-check:
	docker run --rm --memory=2g --memory-swap=2g --cpus=2 --network none $(DOCKER_IMAGE) \
		python -c "from slm.telemetry import verify_container_memory_limit; ok, msg, _ = verify_container_memory_limit(); print(msg); exit(0 if ok else 1)"

lowmem-test:
	docker run --rm --memory=2g --memory-swap=2g --cpus=2 --network none \
		-v $(CURDIR)/data:/app/data \
		$(DOCKER_IMAGE) \
		python -m pytest tests/ -m "not slow" -v --tb=short

lowmem-eval:
	docker run --rm --memory=2g --memory-swap=2g --cpus=2 --network none \
		-v $(CURDIR)/models:/app/models:ro \
		-v $(CURDIR)/data:/app/data \
		$(DOCKER_IMAGE) python eval/eval_planner_300.py

lowmem-profile:
	docker run --rm --memory=2g --memory-swap=2g --cpus=2 --network none \
		-v $(CURDIR)/models:/app/models:ro \
		-v $(CURDIR)/data:/app/data \
		$(DOCKER_IMAGE) python scripts/measure_runtime_profile.py --require-cgroup

lowmem: lowmem-build lowmem-check lowmem-test lowmem-profile

clean:
	rm -f data/vehicle.db
	rm -f data/candump/*.log
	rm -f eval/ground_truth.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
