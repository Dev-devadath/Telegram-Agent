import logging
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def timed_operation(name: str, **context: object) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        context_bits = " ".join(f"{key}={value}" for key, value in context.items())
        suffix = f" {context_bits}" if context_bits else ""
        logger.info("PERF %s took %.1fms%s", name, elapsed_ms, suffix)


class OperationTimer:
    def __init__(self, name: str, **context: object) -> None:
        self.name = name
        self.context = context
        self._start = 0.0

    def __enter__(self) -> "OperationTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        context_bits = " ".join(f"{key}={value}" for key, value in self.context.items())
        suffix = f" {context_bits}" if context_bits else ""
        logger.info("PERF %s took %.1fms%s", self.name, elapsed_ms, suffix)

    def log_step(self, step: str, **context: object) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        merged = {**self.context, **context}
        context_bits = " ".join(f"{key}={value}" for key, value in merged.items())
        suffix = f" {context_bits}" if context_bits else ""
        logger.info("PERF %s.%s at %.1fms%s", self.name, step, elapsed_ms, suffix)
