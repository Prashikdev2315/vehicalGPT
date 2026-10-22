# Stage 1: Build environment for llama-cpp-python and native wheels
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        cmake \
        python3-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Portable CPU compile flags for llama.cpp chosen by TARGETARCH
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        export CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF"; \
    else \
        export CMAKE_ARGS="-DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_AVX=ON -DGGML_NATIVE=OFF"; \
    fi && \
    pip install --no-cache-dir wheel && \
    pip wheel --no-cache-dir --wheel-dir=/build/wheels llama-cpp-python==0.3.36

# Stage 2: Minimal runtime image
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Copy pre-compiled wheels from builder stage
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy project files
COPY pyproject.toml README.md ./
COPY ingest/ ./ingest/
COPY store/ ./store/
COPY insight/ ./insight/
COPY tools/ ./tools/
COPY llm/ ./llm/
COPY slm/ ./slm/
COPY sim/ ./sim/
COPY eval/ ./eval/
COPY ui/ ./ui/
COPY docs/ ./docs/
COPY tests/ ./tests/
COPY fixtures/ ./fixtures/
COPY scripts/ ./scripts/
COPY Makefile ./

# Install project and dev dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run test suite
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
