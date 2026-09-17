"""OpenTelemetry Distributed Tracing & Structured JSON Logging for Architecture Readiness Assessor."""

import functools
import inspect
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# GCP Project Configuration
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ai-readiness-assessor")
PROJECT_NUMBER = os.environ.get("GOOGLE_CLOUD_PROJECT_NUMBER", "123456789012")
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "ai-readiness-assessor")

# Initialize OpenTelemetry TracerProvider with InMemorySpanExporter for UI & Auditability
_resource = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "gcp.project_id": PROJECT_ID,
        "gcp.project_number": PROJECT_NUMBER,
        "service.version": "1.0.0",
    }
)
_tracer_provider = TracerProvider(resource=_resource)
_span_exporter = InMemorySpanExporter()
_tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
trace.set_tracer_provider(_tracer_provider)

tracer = trace.get_tracer("assessor.tracer")

# In-memory ring buffer for structured JSON logs (for UI Observability & CI verification)
_STRUCTURED_LOGS: List[Dict[str, Any]] = []
MAX_LOG_ENTRIES = 500

# Configure standard Python logger to output JSON lines
logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def _get_current_trace_context() -> Dict[str, str]:
    """Extracts current OpenTelemetry trace_id and span_id in hex format."""
    current_span = trace.get_current_span()
    ctx = current_span.get_span_context()
    if ctx and ctx.is_valid:
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    return {"trace_id": "0" * 32, "span_id": "0" * 16}


def log_structured_event(
    event_type: str,
    payload: Dict[str, Any],
    severity: str = "INFO",
    component: str = "agent",
) -> Dict[str, Any]:
    """Emits a Cloud Logging compatible structured JSON event with OpenTelemetry correlation."""
    trace_ctx = _get_current_trace_context()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": severity.upper(),
        "service_name": SERVICE_NAME,
        "gcp_project_id": PROJECT_ID,
        "logging.googleapis.com/trace": f"projects/{PROJECT_ID}/traces/{trace_ctx['trace_id']}",
        "logging.googleapis.com/spanId": trace_ctx["span_id"],
        "trace_id": trace_ctx["trace_id"],
        "span_id": trace_ctx["span_id"],
        "component": component,
        "event_type": event_type,
        "payload": payload,
    }
    _STRUCTURED_LOGS.append(record)
    if len(_STRUCTURED_LOGS) > MAX_LOG_ENTRIES:
        _STRUCTURED_LOGS.pop(0)

    logger.info(json.dumps(record, ensure_ascii=False))
    return record


def log_agent_intent(
    action: str,
    intent: str,
    component: str = "agent",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Explicitly logs the agent's pre-execution intent before performing an action or tool call."""
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attribute("assessor.intent", intent)
        current_span.set_attribute("assessor.intended_action", action)

    payload: Dict[str, Any] = {
        "phase": "pre_execution_intent",
        "action": action,
        "intended_action": intent,
        "status": "INTENT_LOGGED_BEFORE_EXECUTION",
    }
    if details:
        payload.update(details)

    return log_structured_event(
        event_type=f"{action}.intent",
        payload=payload,
        severity="INFO",
        component=component,
    )


def trace_span(name: Optional[str] = None, component: str = "agent") -> Callable:
    """Decorator to instrument sync and async functions with OpenTelemetry spans, pre-execution intent logs, and outcome/error logs."""

    def decorator(func: Callable) -> Callable:
        span_name = name or f"{component}.{func.__name__}"
        intent_desc = (
            func.__doc__.strip().splitlines()[0]
            if func.__doc__
            else f"Execute {span_name} in component {component}"
        )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start_time = time.perf_counter()
                with tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("assessor.component", component)
                    span.set_attribute("assessor.function", func.__name__)
                    span.set_attribute("gcp.project_id", PROJECT_ID)
                    span.set_attribute("assessor.intent", intent_desc)

                    # Pre-execution log capturing explicit intent before action is performed
                    log_structured_event(
                        event_type=f"{span_name}.intent",
                        payload={
                            "phase": "pre_execution_intent",
                            "function": func.__name__,
                            "intended_action": intent_desc,
                            "status": "STARTED",
                        },
                        severity="INFO",
                        component=component,
                    )

                    try:
                        result = await func(*args, **kwargs)
                        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        span.set_attribute("assessor.latency_ms", latency_ms)
                        span.set_attribute("assessor.status", "OK")
                        span.set_attribute("assessor.intent_vs_outcome", "MATCHED")
                        log_structured_event(
                            event_type=f"{span_name}.completed",
                            payload={
                                "function": func.__name__,
                                "intended_action": intent_desc,
                                "actual_outcome": "COMPLETED_SUCCESSFULLY",
                                "intent_vs_outcome": "MATCHED",
                                "latency_ms": latency_ms,
                                "status": "OK",
                            },
                            severity="INFO",
                            component=component,
                        )
                        return result
                    except Exception as exc:
                        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        span.set_attribute("assessor.latency_ms", latency_ms)
                        span.set_attribute("assessor.status", "ERROR")
                        span.set_attribute("assessor.intent_vs_outcome", "ERROR_DIVERGED")
                        span.record_exception(exc)
                        log_structured_event(
                            event_type=f"{span_name}.error",
                            payload={
                                "function": func.__name__,
                                "intended_action": intent_desc,
                                "intent_vs_outcome": "ERROR_DIVERGED",
                                "latency_ms": latency_ms,
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                            },
                            severity="ERROR",
                            component=component,
                        )
                        raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start_time = time.perf_counter()
                with tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("assessor.component", component)
                    span.set_attribute("assessor.function", func.__name__)
                    span.set_attribute("gcp.project_id", PROJECT_ID)
                    span.set_attribute("assessor.intent", intent_desc)

                    # Pre-execution log capturing explicit intent before action is performed
                    log_structured_event(
                        event_type=f"{span_name}.intent",
                        payload={
                            "phase": "pre_execution_intent",
                            "function": func.__name__,
                            "intended_action": intent_desc,
                            "status": "STARTED",
                        },
                        severity="INFO",
                        component=component,
                    )

                    try:
                        result = func(*args, **kwargs)
                        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        span.set_attribute("assessor.latency_ms", latency_ms)
                        span.set_attribute("assessor.status", "OK")
                        span.set_attribute("assessor.intent_vs_outcome", "MATCHED")
                        log_structured_event(
                            event_type=f"{span_name}.completed",
                            payload={
                                "function": func.__name__,
                                "intended_action": intent_desc,
                                "actual_outcome": "COMPLETED_SUCCESSFULLY",
                                "intent_vs_outcome": "MATCHED",
                                "latency_ms": latency_ms,
                                "status": "OK",
                            },
                            severity="INFO",
                            component=component,
                        )
                        return result
                    except Exception as exc:
                        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        span.set_attribute("assessor.latency_ms", latency_ms)
                        span.set_attribute("assessor.status", "ERROR")
                        span.set_attribute("assessor.intent_vs_outcome", "ERROR_DIVERGED")
                        span.record_exception(exc)
                        log_structured_event(
                            event_type=f"{span_name}.error",
                            payload={
                                "function": func.__name__,
                                "intended_action": intent_desc,
                                "intent_vs_outcome": "ERROR_DIVERGED",
                                "latency_ms": latency_ms,
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                            },
                            severity="ERROR",
                            component=component,
                        )
                        raise

            return sync_wrapper

    return decorator


def get_recent_spans() -> List[Dict[str, Any]]:
    """Returns exported OpenTelemetry spans as dictionaries for UI & CI inspection."""
    spans = _span_exporter.get_finished_spans()
    serialized = []
    for s in spans:
        serialized.append(
            {
                "name": s.name,
                "trace_id": format(s.context.trace_id, "032x"),
                "span_id": format(s.context.span_id, "016x"),
                "start_time_ns": s.start_time,
                "end_time_ns": s.end_time,
                "duration_ms": round((s.end_time - s.start_time) / 1e6, 2)
                if s.end_time and s.start_time
                else 0.0,
                "attributes": dict(s.attributes) if s.attributes else {},
                "status": s.status.status_code.name if s.status else "UNSET",
            }
        )
    return serialized


def get_recent_logs() -> List[Dict[str, Any]]:
    """Returns recent structured JSON log entries."""
    return list(_STRUCTURED_LOGS)


def clear_telemetry() -> None:
    """Clears in-memory spans and structured logs (useful between test runs)."""
    _span_exporter.clear()
    _STRUCTURED_LOGS.clear()
