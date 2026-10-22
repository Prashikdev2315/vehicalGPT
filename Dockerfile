FROM python:3.11-slim

WORKDIR /app

# Install system build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY ingest/ ./ingest/
COPY store/ ./store/
COPY insight/ ./insight/
COPY tools/ ./tools/
COPY llm/ ./llm/
COPY sim/ ./sim/
COPY eval/ ./eval/
COPY ui/ ./ui/
COPY docs/ ./docs/
COPY tests/ ./tests/
COPY fixtures/ ./fixtures/
COPY Makefile ./

# Install project and dev dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run tests
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
