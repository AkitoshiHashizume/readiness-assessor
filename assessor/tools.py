"""Google ADK Custom Tools with Pydantic Input Validation, Token Budgeting, & Error Recovery."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ValidationError

from assessor.guardrails import HITLApprovalManager
from assessor.memory import AssessmentMemoryStore, GuidelinesRAG
from assessor.telemetry import log_structured_event, trace_span

# Shared instances
_rag_engine = GuidelinesRAG()
_memory_store = AssessmentMemoryStore()

MAX_TOOL_RESPONSE_CHARS = 3500


def _truncate_payload(text: str, max_chars: int = MAX_TOOL_RESPONSE_CHARS) -> str:
    """Enforces token budget by truncating overly large tool outputs."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[TRUNCATED_TO_FIT_TOKEN_BUDGET]"


# ==============================================================================
# Pydantic Schemas for Strict Input Validation
# ==============================================================================


class GuidelineSearchInput(BaseModel):
    query: str = Field(..., min_length=2, description="Search keywords or architectural concept.")
    category: str = Field(
        default="all",
        description="Filter category: 'all', 'security', 'architecture', 'cost', or 'eval'.",
    )


class ReadinessScoreInput(BaseModel):
    security_score: int = Field(..., ge=0, le=30, description="Gate 1 Security score (0-30).")
    architecture_score: int = Field(
        ..., ge=0, le=30, description="Gate 2 Architecture score (0-30)."
    )
    cost_score: int = Field(..., ge=0, le=20, description="Gate 3 Cost/Tokenomics score (0-20).")
    eval_score: int = Field(..., ge=0, le=20, description="Gate 4 Observability/Eval score (0-20).")


class SaveAssessmentInput(BaseModel):
    project_name: str = Field(..., min_length=2, max_length=120)
    total_score: int = Field(..., ge=0, le=100)
    readiness_status: str = Field(..., pattern=r"^(APPROVED_FOR_POC|PENDING_HUMAN_REVIEW|APPROVED_WITH_CONDITIONS|REJECTED)$")
    summary: str = Field(..., min_length=10)
    security_score: int = Field(default=0, ge=0, le=30)
    architecture_score: int = Field(default=0, ge=0, le=30)
    cost_score: int = Field(default=0, ge=0, le=20)
    eval_score: int = Field(default=0, ge=0, le=20)


class RemediationTemplateInput(BaseModel):
    weak_area: str = Field(
        ...,
        description="Target remediation domain: 'security', 'architecture', 'cost', or 'eval'.",
    )


# ==============================================================================
# ADK Tool Functions
# ==============================================================================


@trace_span(name="tool.search_gcp_guidelines", component="tool")
def search_gcp_guidelines(query: str, category: str = "all") -> Dict[str, Any]:
    """Searches enterprise architecture review guidelines for mandatory requirements and anti-patterns.

    Args:
        query: Architectural terms or review criteria to search (e.g., 'IAM least privilege', 'ADK multi-agent').
        category: Optional gate filter ('all', 'security', 'architecture', 'cost', 'eval').

    Returns:
        Dictionary containing matched guideline sections, citation anchors, and relevance scores.
    """
    try:
        validated = GuidelineSearchInput(query=query, category=category)
        results = _rag_engine.search(
            query=validated.query, category=validated.category, top_k=2
        )
        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "section_title": r["section_title"],
                    "category": r["category"],
                    "citation_url": r["citation_url"],
                    "relevance_score": r["relevance_score"],
                    "content": _truncate_payload(r["content"], 1500),
                }
            )

        return {
            "status": "success",
            "query": validated.query,
            "category": validated.category,
            "matched_count": len(formatted_results),
            "guidelines": formatted_results,
        }
    except ValidationError as ve:
        return {
            "status": "error",
            "error_code": "INVALID_SEARCH_PARAMETERS",
            "message": str(ve),
            "recovery_guidance": "Provide a non-empty 'query' string (at least 2 chars) and valid category ('all', 'security', 'architecture', 'cost', 'eval').",
        }
    except Exception as exc:
        return {
            "status": "error",
            "error_code": "RAG_SEARCH_FAILED",
            "message": str(exc),
            "recovery_guidance": "Retry with a simpler keyword query or set category='all'.",
        }


@trace_span(name="tool.calculate_readiness_score", component="tool")
def calculate_readiness_score(
    security_score: int,
    architecture_score: int,
    cost_score: int,
    eval_score: int,
) -> Dict[str, Any]:
    """Deterministically calculates total PoC readiness score and evaluates Human-in-the-Loop gates.

    Args:
        security_score: Gate 1 Security & Governance score (0 to 30 max).
        architecture_score: Gate 2 Architecture & Scalability score (0 to 30 max).
        cost_score: Gate 3 Tokenomics & Cost Efficiency score (0 to 20 max).
        eval_score: Gate 4 Observability & Eval Readiness score (0 to 20 max).

    Returns:
        Dictionary containing total_score (0-100), readiness_status, gate breakdown, and HITL escalation details.
    """
    try:
        validated = ReadinessScoreInput(
            security_score=int(security_score),
            architecture_score=int(architecture_score),
            cost_score=int(cost_score),
            eval_score=int(eval_score),
        )
        total = (
            validated.security_score
            + validated.architecture_score
            + validated.cost_score
            + validated.eval_score
        )
        hitl_eval = HITLApprovalManager.evaluate_hitl_gate(
            total_score=total, security_score=validated.security_score
        )

        weak_areas = []
        if validated.security_score < 22:
            weak_areas.append("security")
        if validated.architecture_score < 22:
            weak_areas.append("architecture")
        if validated.cost_score < 15:
            weak_areas.append("cost")
        if validated.eval_score < 15:
            weak_areas.append("eval")

        return {
            "status": "success",
            "total_score": total,
            "max_possible_score": 100,
            "readiness_status": hitl_eval["readiness_status"],
            "requires_human_review": hitl_eval["requires_human_review"],
            "escalation_reasons": hitl_eval["escalation_reasons"],
            "action_required": hitl_eval["action_required"],
            "breakdown": {
                "gate_1_security": {"score": validated.security_score, "max": 30},
                "gate_2_architecture": {"score": validated.architecture_score, "max": 30},
                "gate_3_cost": {"score": validated.cost_score, "max": 20},
                "gate_4_eval": {"score": validated.eval_score, "max": 20},
            },
            "identified_weak_areas": weak_areas,
        }
    except (ValidationError, ValueError) as ve:
        return {
            "status": "error",
            "error_code": "SCORE_OUT_OF_RANGE",
            "message": str(ve),
            "recovery_guidance": "Ensure scores are integers within valid bounds: security_score (0-30), architecture_score (0-30), cost_score (0-20), eval_score (0-20).",
        }


@trace_span(name="tool.save_assessment_record", component="tool")
def save_assessment_record(
    project_name: str,
    total_score: int,
    readiness_status: str,
    summary: str,
    security_score: int = 0,
    architecture_score: int = 0,
    cost_score: int = 0,
    eval_score: int = 0,
) -> Dict[str, Any]:
    """Persists the completed readiness assessment record into SQLite long-term memory.

    Args:
        project_name: Name of the customer engagement or PoC project.
        total_score: Calculated total score (0-100).
        readiness_status: Status string ('APPROVED_FOR_POC' or 'PENDING_HUMAN_REVIEW').
        summary: Executive summary of strengths, risks, and gate evaluations.
        security_score: Gate 1 score (0-30).
        architecture_score: Gate 2 score (0-30).
        cost_score: Gate 3 score (0-20).
        eval_score: Gate 4 score (0-20).

    Returns:
        Dictionary with saved record metadata including database record_id.
    """
    try:
        validated = SaveAssessmentInput(
            project_name=project_name,
            total_score=int(total_score),
            readiness_status=readiness_status,
            summary=summary,
            security_score=int(security_score),
            architecture_score=int(architecture_score),
            cost_score=int(cost_score),
            eval_score=int(eval_score),
        )
        saved = _memory_store.save_assessment(
            project_name=validated.project_name,
            total_score=validated.total_score,
            readiness_status=validated.readiness_status,
            summary=validated.summary,
            security_score=validated.security_score,
            architecture_score=validated.architecture_score,
            cost_score=validated.cost_score,
            eval_score=validated.eval_score,
        )
        return {
            "status": "success",
            "record_id": saved.get("id"),
            "project_name": saved.get("project_name"),
            "readiness_status": saved.get("readiness_status"),
            "created_at": saved.get("created_at"),
            "message": f"Assessment record #{saved.get('id')} saved to persistent SQLite store.",
        }
    except (ValidationError, ValueError) as ve:
        return {
            "status": "error",
            "error_code": "INVALID_ASSESSMENT_RECORD",
            "message": str(ve),
            "recovery_guidance": "Verify readiness_status is one of ['APPROVED_FOR_POC', 'PENDING_HUMAN_REVIEW', 'APPROVED_WITH_CONDITIONS'] and summary has >= 10 characters.",
        }


_REMEDIATION_TEMPLATES: Dict[str, Dict[str, str]] = {
    "security": {
        "title": "Gate 1 Remediation: Cloud IAM Least Privilege & Model Armor Guardrails",
        "citation": "sample_data/architecture_guidelines.md#gate-1-security--governance",
        "code_snippet": """# Terraform: Scoped Service Account for Cloud Run ADK Agent
resource "google_service_account" "adk_agent_sa" {
  account_id   = "assessor-runtime-sa"
  display_name = "Least-Privilege ADK Runtime SA"
  project      = var.project_id
}

resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.adk_agent_sa.email}"
}""",
    },
    "architecture": {
        "title": "Gate 2 Remediation: Google ADK Multi-Agent & Pydantic Schema Enforcement",
        "citation": "sample_data/architecture_guidelines.md#gate-2-architecture--scalability",
        "code_snippet": """# Python ADK: Structured Multi-Agent with Pydantic Output Schema
from google.adk.agents import LlmAgent
from pydantic import BaseModel

class AuditOutput(BaseModel):
    total_score: int
    readiness_status: str

auditor_agent = LlmAgent(
    name="ArchitectureAuditAgent",
    model="gemini-2.5-pro",
    output_schema=AuditOutput,
)""",
    },
    "cost": {
        "title": "Gate 3 Remediation: Tiered Model Routing & ADK FallbackModel Resilience",
        "citation": "sample_data/architecture_guidelines.md#gate-3-tokenomics--cost-efficiency",
        "code_snippet": """# Python ADK: Model Failover & Tiered Routing (Pro -> Flash-Lite)
from google.adk.models import FallbackModel, Gemini
from google.genai import types

retry_cfg = types.HttpRetryOptions(attempts=3, initial_delay=1.0, exp_base=2.0)
resilient_model = FallbackModel(
    models=[
        Gemini(model="gemini-2.5-pro", retry_options=retry_cfg),
        Gemini(model="gemini-3.5-flash", retry_options=retry_cfg),
    ]
)""",
    },
    "eval": {
        "title": "Gate 4 Remediation: OpenTelemetry Tracing & Golden Dataset CI/CD Pipeline",
        "citation": "sample_data/architecture_guidelines.md#gate-4-observability--eval-readiness",
        "code_snippet": """# Python OpenTelemetry Span Instrumentation for ADK Tool Execution
from opentelemetry import trace
tracer = trace.get_tracer("assessor.tracer")

with tracer.start_as_current_span("agent.audit_proposal") as span:
    span.set_attribute("gcp.project_id", "ai-readiness-assessor")
    span.set_attribute("assessor.gate", "observability")""",
    },
}


@trace_span(name="tool.get_remediation_template", component="tool")
def get_remediation_template(weak_area: str) -> Dict[str, Any]:
    """Retrieves production-ready Google Cloud / ADK / Terraform remediation templates for a weak gate.

    Args:
        weak_area: One of 'security', 'architecture', 'cost', or 'eval'.

    Returns:
        Dictionary with remediation title, guideline citation anchor, and copy-pasteable code snippet.
    """
    try:
        validated = RemediationTemplateInput(weak_area=weak_area)
        key = validated.weak_area.lower().strip()
        # Map synonyms
        if "sec" in key or "iam" in key or "gov" in key:
            key = "security"
        elif "arch" in key or "scale" in key or "adk" in key:
            key = "architecture"
        elif "cost" in key or "token" in key or "finops" in key:
            key = "cost"
        elif "eval" in key or "obs" in key or "trace" in key:
            key = "eval"

        if key not in _REMEDIATION_TEMPLATES:
            return {
                "status": "error",
                "error_code": "UNKNOWN_WEAK_AREA",
                "message": f"Unsupported weak_area '{weak_area}'.",
                "recovery_guidance": "Specify one of: 'security', 'architecture', 'cost', or 'eval'.",
            }

        tmpl = _REMEDIATION_TEMPLATES[key]
        return {
            "status": "success",
            "weak_area": key,
            "title": tmpl["title"],
            "citation": tmpl["citation"],
            "code_snippet": tmpl["code_snippet"],
        }
    except ValidationError as ve:
        return {
            "status": "error",
            "error_code": "INVALID_REMEDIATION_INPUT",
            "message": str(ve),
            "recovery_guidance": "Pass a valid string for 'weak_area' ('security', 'architecture', 'cost', 'eval').",
        }
