"""Input/Output Guardrails (PII Redaction & Prompt Injection Defense) & HITL Approval Manager."""

import re
from typing import Any, Dict, List, Optional, Tuple

from assessor.telemetry import log_structured_event, trace_span


class PromptInjectionError(ValueError):
    """Raised when adversarial prompt injection is detected in user input."""


# Regex patterns for PII & Secret Redaction
_PII_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("API_KEY", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    (
        "GCP_SA_KEY",
        re.compile(r"-----BEGIN PRIVATE KEY-----[\s\S]*?-----END PRIVATE KEY-----"),
    ),
    (
        "EMAIL",
        re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
    ),
    (
        "PHONE",
        re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
    ),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

# Adversarial Prompt Injection signatures
_INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (
        "IGNORE_INSTRUCTIONS",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "DISREGARD_RULES",
        re.compile(
            r"disregard\s+(?:all\s+)?(?:previous|prior|system|security)\s+(?:instructions|rules|guidelines)",
            re.IGNORECASE,
        ),
    ),
    (
        "SYSTEM_PROMPT_LEAK",
        re.compile(
            r"(?:reveal|print|output|show|repeat)\s+(?:your|the)\s+(?:system\s+prompt|hidden\s+instructions)",
            re.IGNORECASE,
        ),
    ),
    (
        "FORCE_APPROVAL_OVERRIDE",
        re.compile(
            r"(?:you\s+must\s+output|force\s+status\s+to)\s+(?:APPROVED_FOR_POC|score\s+100)",
            re.IGNORECASE,
        ),
    ),
]


@trace_span(name="guardrails.redact_pii", component="guardrails")
def redact_pii(text: str) -> Tuple[str, List[str]]:
    """Scans input text and replaces sensitive PII/credentials with [REDACTED_PII:<TYPE>].

    Returns:
        Tuple of (sanitized_text, list_of_redacted_types).
    """
    if not text:
        return "", []

    sanitized = text
    redacted_types: List[str] = []

    for label, pattern in _PII_PATTERNS:
        matches = pattern.findall(sanitized)
        if matches:
            redacted_types.append(label)
            sanitized = pattern.sub(f"[REDACTED_PII:{label}]", sanitized)

    if redacted_types:
        log_structured_event(
            event_type="guardrails.pii_redacted",
            payload={"redacted_categories": redacted_types, "count": len(redacted_types)},
            severity="WARNING",
            component="guardrails",
        )

    return sanitized, redacted_types


@trace_span(name="guardrails.check_prompt_injection", component="guardrails")
def check_prompt_injection(text: str, raise_on_detect: bool = True) -> Dict[str, Any]:
    """Detects adversarial prompt injection attempts before invoking Vertex AI models.

    Args:
        text: User proposal or prompt text.
        raise_on_detect: If True, raises PromptInjectionError on detection.

    Returns:
        Dict with keys: safe (bool), detected_patterns (List[str]), message (str).
    """
    detected: List[str] = []
    for label, pattern in _INJECTION_PATTERNS:
        if pattern.search(text or ""):
            detected.append(label)

    is_safe = len(detected) == 0
    result = {
        "safe": is_safe,
        "detected_patterns": detected,
        "message": "Input passed security guardrail validation."
        if is_safe
        else f"Blocked adversarial prompt injection patterns: {', '.join(detected)}",
    }

    if not is_safe:
        log_structured_event(
            event_type="guardrails.prompt_injection_blocked",
            payload={"detected_patterns": detected},
            severity="ERROR",
            component="guardrails",
        )
        if raise_on_detect:
            raise PromptInjectionError(result["message"])

    return result


def sanitize_and_validate_input(text: str) -> Dict[str, Any]:
    """Combined guardrail pipeline: checks prompt injection first, then redacts PII."""
    injection_check = check_prompt_injection(text, raise_on_detect=True)
    sanitized_text, redacted_types = redact_pii(text)
    return {
        "sanitized_text": sanitized_text,
        "redacted_pii_types": redacted_types,
        "injection_check": injection_check,
    }


class HITLApprovalManager:
    """Manages Human-in-the-Loop (HITL) escalation and Lead Architect override approvals."""

    SCORE_THRESHOLD = 70
    SECURITY_MIN_THRESHOLD = 20

    @classmethod
    @trace_span(name="guardrails.evaluate_hitl_gate", component="hitl")
    def evaluate_hitl_gate(
        cls, total_score: int, security_score: int
    ) -> Dict[str, Any]:
        """Determines whether an assessment requires Human-in-the-Loop escalation."""
        requires_hitl = (
            total_score < cls.SCORE_THRESHOLD
            or security_score < cls.SECURITY_MIN_THRESHOLD
        )

        reasons: List[str] = []
        if total_score < cls.SCORE_THRESHOLD:
            reasons.append(
                f"Total readiness score ({total_score}/100) is below auto-approval threshold ({cls.SCORE_THRESHOLD})."
            )
        if security_score < cls.SECURITY_MIN_THRESHOLD:
            reasons.append(
                f"Security & Governance score ({security_score}/30) is below mandatory minimum ({cls.SECURITY_MIN_THRESHOLD})."
            )

        if requires_hitl:
            status = "PENDING_HUMAN_REVIEW"
            action_required = (
                "Lead Architect must review architectural risks and explicitly execute "
                "HITL Override Approval before PoC resources can be provisioned."
            )
        else:
            status = "APPROVED_FOR_POC"
            action_required = "None. Proposal meets all technical readiness gates."

        result = {
            "readiness_status": status,
            "requires_human_review": requires_hitl,
            "escalation_reasons": reasons,
            "action_required": action_required,
        }

        log_structured_event(
            event_type="hitl.gate_evaluated",
            payload=result,
            severity="WARNING" if requires_hitl else "INFO",
            component="hitl",
        )
        return result

    @classmethod
    @trace_span(name="guardrails.override_and_approve", component="hitl")
    def override_and_approve(
        cls,
        record_id: int,
        reviewer_email: str,
        justification: str,
        memory_store: Any,
    ) -> Dict[str, Any]:
        """Allows a Lead Architect to manually override a PENDING_HUMAN_REVIEW lock."""
        if not reviewer_email or "@" not in reviewer_email:
            raise ValueError("Valid Lead Architect reviewer email is required for HITL override.")
        if not justification or len(justification.strip()) < 10:
            raise ValueError(
                "Justification must be at least 10 characters explaining risk mitigation."
            )

        updated = memory_store.approve_assessment(
            record_id=record_id,
            reviewer_email=reviewer_email.strip(),
            justification=justification.strip(),
        )

        log_structured_event(
            event_type="hitl.manual_override_approved",
            payload={
                "record_id": record_id,
                "reviewer_email": reviewer_email,
                "new_status": "APPROVED_WITH_CONDITIONS",
                "justification": justification,
            },
            severity="INFO",
            component="hitl",
        )
        return updated
