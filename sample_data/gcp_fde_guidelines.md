# Google Cloud Forward Deployed Engineering (FDE) Engagement Readiness Guidelines

This document defines the mandatory technical review standards enforced by Google Cloud Forward Deployed Engineers (FDEs) before approving any customer Proof-of-Concept (PoC) or Production AI engagement request (ER).

---

## Gate 1: Security & Governance
<!-- Anchor: #gate-1-security--governance -->

### Mandatory Requirements
1. **Zero Hardcoded Credentials**: All Vertex AI and Google Cloud service invocations MUST use Application Default Credentials (ADC) or Workload Identity Federation. Hardcoded `GEMINI_API_KEY` or service account JSON keys in source repositories result in immediate **NO_GO**.
2. **Principle of Least Privilege (Cloud IAM)**: Service accounts deployed to Cloud Run or GKE must only hold scoped roles (`roles/aiplatform.user`, `roles/logging.logWriter`, `roles/cloudtrace.agent`). Use of `roles/owner` or `roles/editor` is strictly prohibited.
3. **Input Guardrails & Prompt Injection Defense**: All user-facing endpoints must implement pre-execution validation (Google Cloud Model Armor or deterministic regex/semantic guardrails) to detect prompt injection (`ignore previous instructions`, `system prompt leak`) and sanitize PII (credit card numbers, SSNs, email addresses).
4. **Data Residency & VPC Service Controls**: Enterprise workloads handling regulated data must specify regional endpoints (e.g., `us-central1`) with zero data retention enabled on Vertex AI endpoints.

### Evaluation Keywords & Anti-Patterns
- **Required Indicators**: `IAM`, `ADC`, `Least Privilege`, `Model Armor`, `Guardrail`, `PII Redaction`, `VPC-SC`.
- **Critical Anti-Patterns (Triggers NO_GO or CONDITIONAL_GO)**: Unfiltered raw user prompts passed directly to LLM system instructions; API keys stored in plaintext config files; absence of prompt injection blocking.

---

## Gate 2: Architecture & Scalability
<!-- Anchor: #gate-2-architecture--scalability -->

### Mandatory Requirements
1. **Framework Standardization (Google ADK)**: Multi-agent workflows must be built on the official Google Agent Development Kit (`google-adk`) using explicit orchestration primitives (`SequentialAgent`, `LoopAgent`, `ParallelAgent`, or `LlmAgent` sub-agents) rather than fragile ad-hoc prompt chaining.
2. **Stateful Session & Context Compaction**: Agents must persist conversation and audit state in a durable store (Cloud SQL, Spanner, Firestore, or SQLite for local/edge containers) and implement context window compaction (`ContextCompactor`) to prevent context bloat and "Lost in the Middle" degradation during multi-turn engagements.
3. **Serverless Autoscaling Compute**: Agent runtimes must be containerized (`Dockerfile`) and deployed to stateless autoscaling compute platforms (Google Cloud Run or GKE Autopilot) with Infrastructure-as-Code (`Terraform`) defining all resources.
4. **Strict Structured Output Schemas**: Inter-agent handoffs and final decision payloads must enforce `Pydantic` (`BaseModel`) validation schemas to eliminate downstream parsing failures.

### Evaluation Keywords & Anti-Patterns
- **Required Indicators**: `Google ADK`, `SequentialAgent`, `LoopAgent`, `Cloud Run`, `Terraform`, `Pydantic`, `Stateful Memory`, `Context Compaction`.
- **Critical Anti-Patterns**: Monolithic single-prompt architectures attempting complex multi-step reasoning; unvalidated free-text JSON parsing via regex; stateful in-memory-only globals that break horizontal scaling.

---

## Gate 3: Tokenomics & Cost Efficiency
<!-- Anchor: #gate-3-tokenomics--cost-efficiency -->

### Mandatory Requirements
1. **Tiered Model Routing (Pro vs. Flash/Lite)**: Systems must not use flagship reasoning models (`gemini-2.5-pro`) for simple extraction, formatting, or classification tasks. High-volume ingestion, guardrail checks, and critique loops must route to cost-efficient models (`gemini-3.5-flash` or `gemini-3.5-flash-lite`), reserving `gemini-2.5-pro` for final synthesis and complex architectural judgment.
2. **Resilience & Native Failover (`FallbackModel`)**: Production agents must configure HTTP exponential backoff (`HttpRetryOptions` for HTTP 429/503 errors) and native model failover (`FallbackModel`) so traffic seamlessly falls back from primary endpoints to secondary models without service interruption.
3. **Token Budget Enforcement**: Tools and RAG retrievers must truncate retrieved chunks and enforce strict token budgets per turn (< 4,000 tokens per tool response) to bound latency and FinOps cost per engagement review.

### Evaluation Keywords & Anti-Patterns
- **Required Indicators**: `gemini-2.5-pro`, `gemini-3.5-flash-lite`, `FallbackModel`, `HttpRetryOptions`, `Token Budget`, `FinOps`, `Cost Routing`.
- **Critical Anti-Patterns**: Using `gemini-2.5-pro` for every sub-task without cost routing; lack of retry/backoff handling on Vertex AI quota exhaustion (`429 Too Many Requests`).

---

## Gate 4: Observability & Eval Readiness
<!-- Anchor: #gate-4-observability--eval-readiness -->

### Mandatory Requirements
1. **OpenTelemetry Distributed Tracing**: Every agent invocation, tool execution, RAG retrieval, and self-correction loop must emit OpenTelemetry (`opentelemetry-api` / `opentelemetry-sdk`) spans with structured attributes (`engagement_id`, `gate_name`, `model_name`, `latency_ms`, `token_count`).
2. **Structured JSON Telemetry**: Logs must be emitted in structured JSON format compatible with Google Cloud Logging (`severity`, `trace_id`, `span_id`, `component`, `event_type`) to enable automated alerting and BigQuery sink analytics.
3. **Golden Dataset CI/CD Evaluation**: Repositories must include an automated test suite (`pytest`) featuring a Golden Dataset of representative customer proposals (covering `GO`, `CONDITIONAL_GO`, and `NO_GO` scenarios) and adversarial prompt injection tests executed automatically via GitHub Actions CI.

### Evaluation Keywords & Anti-Patterns
- **Required Indicators**: `OpenTelemetry`, `Distributed Tracing`, `Structured JSON Logging`, `Golden Dataset`, `pytest`, `GitHub Actions CI/CD`.
- **Critical Anti-Patterns**: `print()` debugging in production code; deploying agent prompts without automated regression testing against a Golden Dataset.
