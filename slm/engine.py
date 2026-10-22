"""Edge SLM Runtime Engine for VehicleGPT using llama-cpp-python."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Generator

try:
    import llama_cpp
    from llama_cpp.llama_cache import LlamaRAMCache
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    llama_cpp = None
    LlamaRAMCache = None

from slm.telemetry import get_process_rss_mb

DEFAULT_MODEL_PATH = Path("models/qwen2.5-1.5b-instruct-q4_k_m.gguf")


def get_model_path() -> Path:
    """Return configured model path, checking env var and default directory."""
    env_path = os.getenv("VEHICLEGPT_MODEL_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    return DEFAULT_MODEL_PATH


_GLOBAL_ENGINE: SLMEngine | None = None


def get_slm_engine(
    model_path: Path | str | None = None,
    n_ctx: int = 2048,
    n_threads: int = 2,
    lazy_load: bool = True,
) -> SLMEngine:
    """Get or create singleton SLMEngine instance."""
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = SLMEngine(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            lazy_load=lazy_load,
        )
    return _GLOBAL_ENGINE


class SLMEngine:
    """Manages on-device GGUF SLM inference with prefix caching and grammar decoding."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        n_ctx: int = 2048,
        n_threads: int = 2,
        use_cache: bool = True,
        lazy_load: bool = True,
    ) -> None:
        self.model_path = Path(model_path) if model_path else get_model_path()
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.use_cache = use_cache
        self._llm: Any = None
        self._load_time_sec: float | None = None

        if not lazy_load:
            self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """Load GGUF weights into memory using llama.cpp."""
        if self._llm is not None:
            return

        if not LLAMA_CPP_AVAILABLE:
            raise RuntimeError("llama-cpp-python is not installed.")

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model file not found at '{self.model_path}'. "
                f"Run 'python scripts/download_model.py' to download the weights."
            )

        t0 = time.perf_counter()
        # Initialize llama.cpp model under 2-thread / CPU envelope
        self._llm = llama_cpp.Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_batch=512,
            verbose=False,
        )

        if self.use_cache and LlamaRAMCache:
            cache = LlamaRAMCache(capacity_bytes=256 * 1024 * 1024)
            self._llm.set_cache(cache)

        self._load_time_sec = round(time.perf_counter() - t0, 3)

    @property
    def is_available(self) -> bool:
        """Return True if model file exists and llama_cpp is importable."""
        return LLAMA_CPP_AVAILABLE and self.model_path.exists()

    @property
    def load_time_sec(self) -> float | None:
        return self._load_time_sec

    def generate(
        self,
        prompt: str,
        grammar: Any = None,
        max_tokens: int = 128,
        temperature: float = 0.0,
        stop: list[str] | None = None,
    ) -> str:
        """Generate full completion text from prompt."""
        self._ensure_loaded()
        stop_tokens = stop or ["<|im_end|>", "<|endoftext|>"]

        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": stop_tokens,
        }
        if grammar is not None:
            kwargs["grammar"] = grammar

        res = self._llm(**kwargs)
        return res["choices"][0]["text"].strip()

    def stream(
        self,
        prompt: str,
        grammar: Any = None,
        max_tokens: int = 256,
        temperature: float = 0.0,
        stop: list[str] | None = None,
    ) -> Generator[str, None, None]:
        """Stream completion tokens as they are decoded."""
        self._ensure_loaded()
        stop_tokens = stop or ["<|im_end|>", "<|endoftext|>"]

        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": stop_tokens,
            "stream": True,
        }
        if grammar is not None:
            kwargs["grammar"] = grammar

        for chunk in self._llm(**kwargs):
            text = chunk["choices"][0].get("text", "")
            if text:
                yield text

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 128,
        temperature: float = 0.0,
    ) -> str:
        """Execute chat completion using model chat template."""
        self._ensure_loaded()
        res = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return res["choices"][0]["message"]["content"].strip()

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 128,
        temperature: float = 0.0,
    ) -> Generator[str, None, None]:
        """Stream chat completion tokens using model chat template."""
        self._ensure_loaded()
        for chunk in self._llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        ):
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content

    def benchmark(
        self,
        prompt: str = "<|im_start|>system\nYou are an automotive diagnostics planner.<|im_end|>\n<|im_start|>user\nCheck battery SOC<|im_end|>\n<|im_start|>assistant\n",
        max_tokens: int = 32,
    ) -> dict[str, Any]:
        """Measure cold load time, prompt tokens/s, generation tokens/s, and memory RSS."""
        cold_load = self.load_time_sec
        if cold_load is None:
            self._ensure_loaded()
            cold_load = self.load_time_sec or 0.0

        t0 = time.perf_counter()
        output = self.generate(prompt=prompt, max_tokens=max_tokens, temperature=0.0)
        dt = time.perf_counter() - t0

        # Rough token count estimate based on completion length
        tok_count = max(len(output.split()), 1)
        gen_tokens_per_sec = round(tok_count / max(dt, 0.001), 2)
        rss_mb = get_process_rss_mb()

        return {
            "model_path": str(self.model_path),
            "load_time_sec": cold_load,
            "generation_time_sec": round(dt, 3),
            "tokens_per_sec": gen_tokens_per_sec,
            "process_rss_mb": rss_mb,
            "output_preview": output[:60],
        }
