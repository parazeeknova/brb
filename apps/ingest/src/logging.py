"""Structured logging for the ho pipeline.

Replaces all print() calls with machine-readable structured logs.
Supports contextual fields (connector, source, entity, worker, event_id,
latency, retry_count, exception).

Levels: DEBUG < INFO < WARNING < ERROR
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    timestamp: str = ""
    level: str = "INFO"
    message: str = ""
    logger: str = "ho"
    # Optional contextual fields
    connector: str = ""
    source: str = ""
    entity: str = ""
    worker: str = ""
    event_id: str = ""
    latency: float | None = None
    retry_count: int | None = None
    exception: str = ""
    # Arbitrary extras
    extra: dict[str, Any] = field(default_factory=dict)


class StructuredLogger:
    def __init__(self, name: str = "ho", min_level: LogLevel = LogLevel.INFO) -> None:
        self.name = name
        self.min_level = min_level
        self._context: dict[str, Any] = {}

    def bind(self, **kwargs: Any) -> StructuredLogger:
        """Return a child logger with extra fields baked in."""
        child = StructuredLogger(self.name, self.min_level)
        child._context = {**self._context, **kwargs}
        return child

    def _emit(self, level: LogLevel, message: str, **kwargs: Any) -> None:
        if level.value < self.min_level.value:
            return

        # Separate known LogEntry fields from arbitrary extras
        known = {
            "timestamp",
            "level",
            "message",
            "logger",
            "connector",
            "source",
            "entity",
            "worker",
            "event_id",
            "latency",
            "retry_count",
            "exception",
            "extra",
        }
        merged = {**self._context, **kwargs}
        entry_kwargs = {k: v for k, v in merged.items() if k in known}
        extra_kwargs = {k: v for k, v in merged.items() if k not in known}
        if extra_kwargs:
            entry_kwargs.setdefault("extra", {}).update(extra_kwargs)

        entry = LogEntry(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            level=level.value,
            message=message,
            logger=self.name,
            **entry_kwargs,
        )

        # Strip empty fields for cleaner output
        payload = {k: v for k, v in asdict(entry).items() if v not in ("", None, {}, [])}

        # JSON to stderr so stdout is free for data piping
        print(json.dumps(payload, default=str), file=sys.stderr)
        # Ship the same record to OpenObserve when enabled (fail-open).
        _otel.emit(level.value, message, {"logger": self.name, **merged})

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._emit(LogLevel.ERROR, message, **kwargs)

    def exception(self, message: str, exc: BaseException | None = None, **kwargs: Any) -> None:
        tb = ""
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._emit(LogLevel.ERROR, message, exception=tb, **kwargs)


# Module-level convenience
_root = StructuredLogger(name="ho")


class _OtelSink:
    """OTLP log shipper (OpenObserve). Fail-open: never breaks logging.

    Enabled when OTEL_ENABLED=1 (pipeline container sets it). Batches in a
    background thread; a dead backend only drops telemetry, never logs.
    """

    def __init__(self) -> None:
        self._logger = None
        if os.environ.get("OTEL_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
            return
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource

            endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
            if not endpoint:
                return
            headers = {}
            for pair in os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").split(","):
                if "=" in pair:
                    key, _, value = pair.partition("=")
                    headers[key.strip()] = value.strip()
            provider = LoggerProvider(
                resource=Resource.create({SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "ho")})
            )
            provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers or None)
                )
            )
            set_logger_provider(provider)
            handler = LoggingHandler(level=0, logger_provider=provider)
            import logging as _stdlib_logging

            self._logger = _stdlib_logging.getLogger("ho.otel")
            self._logger.handlers = [handler]
            self._logger.propagate = False
        except Exception:
            self._logger = None

    def emit(self, level: str, message: str, attrs: dict[str, Any]) -> None:
        if self._logger is None:
            return
        try:
            import logging as _stdlib_logging

            record_level = getattr(_stdlib_logging, level, _stdlib_logging.INFO)
            safe = {k: v for k, v in attrs.items() if isinstance(v, (str, int, float, bool))}
            self._logger.log(record_level, message, extra=safe)
        except Exception:
            pass


_otel = _OtelSink()


def get_logger(name: str) -> StructuredLogger:
    min_level = LogLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    return StructuredLogger(name=name, min_level=min_level)
