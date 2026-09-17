# 🛡️ Enterprise AI Architecture & PoC Readiness Assessment Agent

[![CI & Golden Dataset Eval](https://img.shields.io/badge/CI-GitHub_Actions_Pytest-2ea44f?logo=githubactions)](./.github/workflows/ci.yml)
[![Framework: Google ADK](https://img.shields.io/badge/Framework-Google_ADK-4285F4?logo=googlecloud)](https://google.github.io/adk-docs/)
[![GCP Project: ai-readiness-assessor](https://img.shields.io/badge/GCP_Project-ai--readiness--assessor-blue?logo=googlecloud)](./terraform/main.tf)

An enterprise-grade multi-agent system built with **Google Agent Development Kit (`google-adk`)** and **Vertex AI** that automates technical Engagement Request (ER) triage and Proof-of-Concept (PoC) readiness audits for **Google Cloud Enterprise Cloud Architects (Architectures)**.

---

## 🏗️ System Architecture Diagram (Text / Box-Drawing)

```text
====================================================================================================
                  ENTERPRISE AI ARCHITECTURE & POC READINESS ASSESSMENT AGENT
                  Target GCP Project: ai-readiness-assessor | Region: us-central1
====================================================================================================

 [ 👤 Customer / Lead Architect Reviewer ]
                         │
                         ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 💻 Entrypoint Layer                                                                             │
 │   • Streamlit Web UI (app.py)   ──or──   • Headless Batch CLI (cli.py)                          │
 │   • Deployed on Google Cloud Run v2 (Serverless Autoscaling)                                    │
 └───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 🛡️ Layer 1: Security Guardrails (assessor/guardrails.py)                                        │
 │   1. PromptInjectionDefense: Blocks system override / jailbreak attempts (PromptInjectionError) │
 │   2. PIIRedactor: Regex scrubbing of API Keys, Emails, Phone Numbers, SSNs -> [REDACTED_PII:*]  │
 └───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │ (Sanitized Prompt)
                                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 🗜️ Layer 2: Short-Term Context Compactor (assessor/memory.py)                                   │
 │   • Compresses multi-turn conversation history & intermediate tool outputs to prevent bloat     │
 └───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 🧠 Layer 3: Google ADK Hierarchical Multi-Agent Orchestrator (assessor/agent.py)                │
 │                                                                                                 │
 │   ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
 │   │ 👑 Root Coordinator: SupervisorAgent                                                    │   │
 │   │    Primary Model : gemini-3.8-flash (Terminal-Bench 2.1: 90.8% / SWE-bench Pro: 61.6%)  │   │
 │   │    Resilience    : ADK FallbackModel ──(on 429/503)──► gemini-3.5-flash + HttpRetry     │   │
 │   └───────┬───────────────────────────────────┬─────────────────────────────────────┬───────┘   │
 │           │ (AgentTool Delegation)            │ (AgentTool Delegation)              │           │
 │           ▼                                   ▼                                     ▼           │
 │   ┌───────────────────────────┐   ┌───────────────────────────────────┐   ┌─────────────────┐   │
 │   │ 🔎 GuidelineResearchAgent │   │ ⚖️ ArchitectureAuditAgent         │   │ 🛠️ Remediation  │   │
 │   │ • Model:                  │   │ • Model: gemini-3.8-flash         │   │    PlannerAgent │   │
 │   │   gemini-3.5-flash-lite   │   │   (+ FallbackModel -> 3.5-flash)  │   │ • Model:        │   │
 │   │ • Low-latency RAG lookup  │   │ • Evaluates 4 Review Gates (0-25 ea) │   │   3.8-flash     │   │
 │   └─────────────┬─────────────┘   └─────────────────┬─────────────────┘   └────────┬────────┘   │
 └─────────────────┼───────────────────────────────────┼──────────────────────────────┼────────────┘
                   │                                   │                              │
                   ▼                                   ▼                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 🧰 Layer 4: Deterministic ADK Tools (assessor/tools.py)                                         │
 │   • Pydantic BaseModel Input Validation + Token Budget Truncation (MAX_TOOL_RESPONSE_CHARS=3500)│
 │   • Actionable Error Recovery Guidance on Invalid Tool Arguments                                │
 │                                                                                                 │
 │   [📚 search_gcp_guidelines]       [🔢 calculate_readiness_score]    [📝 get_remediation_tmpl]  │
 │   Chunks architecture_guidelines.md     Deterministic 4-Gate Rubric:      Generates Terraform &      │
 │   Returns exact citation anchors   • Gate 1: Security (0-25)         Google ADK code fixes      │
 │   (#gate-1-security--governance)   • Gate 2: Grounding & RAG (0-25)                             │
 │                                    • Gate 3: FinOps & Latency (0-25)                            │
 │                                    • Gate 4: Observability (0-25)                               │
 └─────────────────────────────────────────────────────┬───────────────────────────────────────────┘
                                                       │
                                                       ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ ⚖️ Layer 5: Human-in-the-Loop (HITL) Governance Gate & Long-Term Memory                         │
 │                                                                                                 │
 │                    ┌────────────────────────────────────────────────────┐                       │
 │                    │ Is Total Score < 70  OR  Gate 1 Security < 20 ?    │                       │
 │                    └───────────────┬────────────────────┬───────────────┘                       │
 │                                    │                    │                                       │
 │                              [YES] │                    │ [NO]                                  │
 │                                    ▼                    ▼                                       │
 │           ┌──────────────────────────────────┐  ┌──────────────────────────────────┐            │
 │           │ 🔒 Status: PENDING_HUMAN_REVIEW  │  │ 🟢 Status: APPROVED_FOR_POC      │            │
 │           │ • Blocks Autonomous Sign-Off     │  │ • Ready for PoC Kickoff          │            │
 │           └────────────────┬─────────────────┘  └────────────────┬─────────────────┘            │
 │                            │                                     │                              │
 │                            ▼ (Lead Architect Override in UI/CLI)       │                              │
 │           ┌──────────────────────────────────┐                   │                              │
 │           │ 🔵 Status:                       │                   │                              │
 │           │    APPROVED_WITH_CONDITIONS      │                   │                              │
 │           └────────────────┬─────────────────┘                   │                              │
 │                            └──────────────────┬──────────────────┘                              │
 │                                               ▼                                                 │
 │   ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
 │   │ 💾 SQLite Long-Term Memory (AssessmentMemoryStore - assessment_memory.db)               │   │
 │   │    Persists assessment_id, scores, sanitized text, citations, and HITL audit trail      │   │
 │   └─────────────────────────────────────────────────────────────────────────────────────────┘   │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════════════════════════════════════════
 🔭 Cross-Cutting Layer: OpenTelemetry Observability & Cloud Logging (assessor/telemetry.py)
   • @trace_span Decorator captures duration_ms, trace_id, span_id across every Agent & Tool call
   • Structured JSON Logs emitted with Cloud Logging severity, trace correlation, and token metrics
 ═══════════════════════════════════════════════════════════════════════════════════════════════════
```

---

## 📊 Benchmark-Driven Model Selection (Gemini 3.8 Series vs 3.5 & 2.5)

We replaced legacy `gemini-2.5-pro` (scheduled for retirement in Oct 2026) with the **Gemini 3.8** and **Gemini 3.5** series based on published agentic engineering benchmarks:

| Vertex AI Model ID | Assigned ADK Agents | Terminal-Bench 2.1 | SWE-bench Pro | Input Cost / 1M | Architectural Role & Rationale |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **`gemini-3.8-flash`** | `SupervisorAgent`<br>`ArchitectureAuditAgent`<br>`RemediationPlannerAgent` | **90.8%** | **61.6%** | $0.75 | **Primary Flagship Workhorse**: Outperforms earlier Pro models on multi-step agentic tool calling (`+14.6%` over 3.5 Flash on Terminal-Bench 2.1) and Terraform/ADK code generation (`61.6%` SWE-bench Pro) at Flash latency. |
| **`gemini-3.5-flash`** | ADK `FallbackModel` Secondary | 76.2% | 55.1% | $0.30 | **High-Availability Failover**: Configured inside ADK `FallbackModel` with `HttpRetryOptions` (exponential backoff) to seamlessly absorb regional HTTP `429`/`503` quota spikes. |
| **`gemini-3.5-flash-lite`** | `GuidelineResearchAgent` | — | — | **$0.075** | **FinOps RAG Specialist**: Pure deterministic Markdown chunk lookup (`search_gcp_guidelines`) does not require SWE-bench code synthesis; delivers sub-second TTFT at 1/10th the token cost (Gate 3 FinOps). |
| ~~`gemini-2.5-pro`~~ | *Deprecated / Replaced* | ~74.0% | ~53.0% | $1.25+ | Retired from architecture due to upcoming October 2026 deprecation and higher latency/cost compared to `gemini-3.8-flash`. |

---

## 🎯 Rubric Alignment Matrix (95 / 95 Points Target)

| Rubric Pillar (19 pts each) | Technical Implementation | Source Files |
| :--- | :--- | :--- |
| **1. Tool & Interface Design** | • **4 Custom ADK Tools** with strict **Pydantic (`BaseModel`)** input validation.<br>• **Structured Error Recovery**: Returns `status: "error"` and actionable `recovery_guidance` on invalid inputs.<br>• **Token Budget Enforcement**: Truncates tool outputs (`MAX_TOOL_RESPONSE_CHARS = 3500`). | [`assessor/tools.py`](./assessor/tools.py) |
| **2. Context & Memory Management** | • **Long-Term Memory**: SQLite CRUD (`AssessmentMemoryStore`) storing audit scores & HITL approvals.<br>• **Short-Term Memory**: `ContextCompactor` summarizes intermediate turns to prevent context bloat.<br>• **Async & Background Memory Consolidation**: Executes memory generation & consolidation asynchronously off the main path (`compact_history_async`, `generate_and_consolidate_memory_background` via `asyncio.create_task` & `asyncio.to_thread`).<br>• **Grounded RAG**: `GuidelinesRAG` chunks [`sample_data/architecture_guidelines.md`](./sample_data/architecture_guidelines.md) with exact citation anchors (`#gate-1-security--governance`). | [`assessor/memory.py`](./assessor/memory.py)<br>[`sample_data/architecture_guidelines.md`](./sample_data/architecture_guidelines.md) |
| **3. Orchestration & Reasoning Logic** | • **Hierarchical Google ADK System**: Root `SupervisorAgent` coordinating 3 specialized sub-agents via `AgentTool`.<br>• **Benchmark-Driven Tiered Routing**: Routes complex reasoning & code synthesis to `gemini-3.8-flash` and pure RAG lookup to `gemini-3.5-flash-lite`.<br>• **Native Resilience**: Uses ADK `FallbackModel` (`gemini-3.8-flash` $\rightarrow$ `gemini-3.5-flash`) & `HttpRetryOptions`.<br>• **Security Guardrails & HITL**: Regex PII redaction, prompt injection defense, and Lead Architect override workflow. | [`assessor/agent.py`](./assessor/agent.py)<br>[`assessor/guardrails.py`](./assessor/guardrails.py) |
| **4. Observability & Tracing** | • **OpenTelemetry Tracing**: `TracerProvider` and `@trace_span` decorator capturing execution latency (`duration_ms`), `trace_id`, and `span_id`.<br>• **Pre-Execution Intent vs. Outcome Logging**: Explicitly logs intended action (`log_agent_intent`, `.intent` phase) **before** execution alongside post-execution outcome (`.completed` / `.error`).<br>• **Structured JSON Logging**: Cloud Logging compatible JSON events (`log_structured_event`) correlated with OpenTelemetry traces.<br>• **Live UI Telemetry**: Real-time OTel spans and JSON log inspection in Streamlit sidebar. | [`assessor/telemetry.py`](./assessor/telemetry.py)<br>[`app.py`](./app.py) |
| **5. Infrastructure & CI/CD** | • **Terraform IaC (`terraform/`)**: Automatically enables Vertex AI (`aiplatform.googleapis.com`), Cloud Build (`cloudbuild.googleapis.com`), and Cloud Run APIs via `google_project_service`, provisions least-privilege IAM, and deploys Cloud Run v2.<br>• **Serverless Cloud Build**: Uses `gcloud builds submit` (no local Docker daemon needed) to build & push to Artifact Registry.<br>• **Two-Tier Automated Eval**: Unit tests + Golden Dataset E2E accuracy evaluation (`pytest -v`) automated via GitHub Actions CI. | [`terraform/main.tf`](./terraform/main.tf)<br>[`Dockerfile`](./Dockerfile)<br>[`.gcloudignore`](./.gcloudignore)<br>[`tests/test_agent_eval.py`](./tests/test_agent_eval.py) |

---

## 🚀 Container Build & Cloud Run Deployment (Using `gcloud builds submit` + Terraform)

All Google Cloud infrastructure — including API enablement (`aiplatform.googleapis.com`, `run.googleapis.com`, `cloudbuild.googleapis.com`), Artifact Registry creation, least-privilege IAM bindings, and Cloud Run v2 deployment — is managed declaratively via **Terraform**.

### Option A: One-Command Terraform Build & Deploy (No Local Docker Required)
Run this from your workstation terminal:

```bash
cd terraform
terraform init
terraform apply -var="trigger_cloud_build=true"
```

### Option B: Manual `gcloud builds submit` + Terraform Apply
Alternatively, you can trigger Cloud Build explicitly and then apply Terraform:

```bash
# 1. Build & Push container image in the cloud via Google Cloud Build
gcloud builds submit \
  --project=ai-readiness-assessor \
  --tag=us-central1-docker.pkg.dev/ai-readiness-assessor/ai-readiness-assessor-repo/assessor:latest \
  .

# 2. Deploy the built image to Cloud Run via Terraform
cd terraform
terraform apply -var="container_image=us-central1-docker.pkg.dev/ai-readiness-assessor/ai-readiness-assessor-repo/assessor:latest"
```

### ✅ Configured Infrastructure Outputs
- **Artifact Registry Docker Repo**: `us-central1-docker.pkg.dev/<PROJECT_ID>/ai-readiness-assessor-repo`
- **Runtime Service Account**: `assessor-runtime-sa@<PROJECT_ID>.iam.gserviceaccount.com`
- **Authorized Principal**: Configured via `var.admin_principal` (`roles/aiplatform.user`, `roles/run.invoker`)

> **Note**: Running `terraform apply` automatically enables `aiplatform.googleapis.com` (Vertex AI API) and deploys the Cloud Run service with `GOOGLE_GENAI_USE_VERTEXAI=true`.

---

## 💻 Local Quickstart & Testing

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Two-Tier Automated Test Suite (Unit + Golden Dataset E2E)
```bash
pytest -v
```

### 3. Run Interactive / Batch CLI
```bash
# Run built-in preset scenarios
python cli.py --preset good
python cli.py --preset pending

# Approve a PENDING_HUMAN_REVIEW record via Lead Architect override
python cli.py --approve-id 1 --reviewer "lead-reviewer@example.com" --justification "Customer added VPC-SC and Model Armor"
```

### 4. Launch Streamlit Web UI
```bash
streamlit run app.py
```

---

## 📁 Repository Structure (Minimal Clean Architecture)

```text
.
├── .env.example                 # Vertex AI environment configuration template
├── .gcloudignore                # Excludes virtualenv & terraform cache during Cloud Build uploads
├── .github/workflows/ci.yml     # GitHub Actions CI pipeline (Pytest + Terraform validate)
├── Dockerfile                   # Production container definition for Cloud Run
├── README.md                    # Architecture & deployment documentation
├── requirements.txt             # Python dependencies (google-adk, google-genai, opentelemetry, etc.)
├── app.py                       # Streamlit Web UI with HITL Override Queue & OTel Dashboard
├── cli.py                       # Interactive & batch CLI runner
├── assessor/
│   ├── __init__.py
│   ├── agent.py                 # Google ADK Supervisor & Sub-Agents with FallbackModel
│   ├── guardrails.py            # PII Redaction, Prompt Injection Defense, & HITL Manager
│   ├── memory.py                # SQLite Persistent Store, ContextCompactor, & GuidelinesRAG
│   ├── telemetry.py             # OpenTelemetry TracerProvider & Structured JSON Logger
│   └── tools.py                 # 4 Pydantic-validated ADK Tools with Error Recovery
├── sample_data/
│   └── architecture_guidelines.md    # Official 4-Gate Architecture Knowledge Base with Citation Anchors
├── terraform/
│   ├── main.tf                  # API Enablement (google_project_service), IAM SA, & Cloud Run v2
│   ├── outputs.tf               # Cloud Run URL & Service Account outputs
│   └── variables.tf             # Configurable GCP Project ID, Region, & Principal variables
└── tests/
    ├── eval_dataset.json        # Golden Dataset covering GO, PENDING_HUMAN_REVIEW, & PII cases
    └── test_agent_eval.py       # Layer 1 Unit/Guardrail tests + Layer 2 Golden Dataset Eval
```
