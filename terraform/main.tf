terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# 1. Enable Required Google Cloud APIs via Terraform
# ==============================================================================

locals {
  should_build = var.trigger_cloud_build

  required_apis = [
    "aiplatform.googleapis.com",       # Vertex AI API (Gemini 3.8 Flash / 3.5 Flash-Lite)
    "run.googleapis.com",              # Cloud Run Admin API
    "iam.googleapis.com",              # Identity & Access Management API
    "logging.googleapis.com",          # Cloud Logging API (Structured JSON logs)
    "cloudtrace.googleapis.com",       # Cloud Trace API (OpenTelemetry spans)
    "artifactregistry.googleapis.com", # Artifact Registry for Docker images
    "cloudbuild.googleapis.com",       # Cloud Build API (Serverless container builds)
    "storage.googleapis.com",          # Cloud Storage API (Source tarball staging for Cloud Build)
  ]
}

resource "google_project_service" "enabled_apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ==============================================================================
# 2. Artifact Registry Repository for Container Images
# ==============================================================================

resource "google_artifact_registry_repository" "assessor_repo" {
  location      = var.region
  repository_id = "${var.service_name}-repo"
  description   = "Docker repository for Enterprise AI Architecture & PoC Readiness Assessment Agent"
  format        = "DOCKER"
  project       = var.project_id

  depends_on = [
    google_project_service.enabled_apis["artifactregistry.googleapis.com"]
  ]
}

# ==============================================================================
# 3. Least-Privilege Service Account & IAM Bindings (Gate 1 Compliance)
# ==============================================================================

resource "google_service_account" "adk_runtime_sa" {
  account_id   = var.service_account_id
  display_name = "AI Readiness Assessor ADK Runtime Service Account"
  description  = "Least-privilege runtime SA for Vertex AI and OpenTelemetry telemetry"
  project      = var.project_id

  depends_on = [
    google_project_service.enabled_apis["iam.googleapis.com"]
  ]
}

# Scoped IAM Roles for Cloud Run Runtime SA
locals {
  sa_roles = [
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ]
}

resource "google_project_iam_member" "adk_runtime_iam" {
  for_each = toset(local.sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.adk_runtime_sa.email}"
}

# Grant IAM Roles to Admin Principal (var.admin_principal)
# Enables local execution & serverless Cloud Build submission via gcloud builds submit
resource "google_project_iam_member" "admin_principal_iam" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/storage.admin",
    "roles/iam.serviceAccountUser",
  ])
  project = var.project_id
  role    = each.value
  member  = var.admin_principal
}

# Grant Cloud Build worker roles to default Compute Engine Service Account (PROJECT_NUMBER-compute@developer.gserviceaccount.com)
# Required because gcloud builds submit uses this default SA to read source tarballs from gs://..._cloudbuild and push to Artifact Registry
resource "google_project_iam_member" "cloudbuild_compute_sa_iam" {
  for_each = toset([
    "roles/storage.admin",
    "roles/artifactregistry.writer",
    "roles/logging.logWriter",
    "roles/cloudbuild.builds.builder",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# ==============================================================================
# 4. Serverless Container Build via gcloud builds submit (No local Docker needed)
# ==============================================================================

resource "terraform_data" "serverless_container_build" {
  count = local.should_build ? 1 : 0

  triggers_replace = [
    filemd5("${path.module}/../Dockerfile"),
    filemd5("${path.module}/../app.py"),
    filemd5("${path.module}/../assessor/agent.py"),
  ]

  provisioner "local-exec" {
    command = "for i in 1 2 3 4 5 6; do sleep 15 && gcloud builds submit --project=${var.project_id} --tag=${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}-repo/assessor:latest ${path.module}/.. && exit 0 || echo \"Attempt $i failed (waiting for GCP IAM propagation or network retry)...\"; done; exit 1"
  }

  depends_on = [
    google_project_service.enabled_apis["cloudbuild.googleapis.com"],
    google_project_service.enabled_apis["storage.googleapis.com"],
    google_artifact_registry_repository.assessor_repo,
    google_project_iam_member.admin_principal_iam,
    google_project_iam_member.cloudbuild_compute_sa_iam,
  ]
}

# ==============================================================================
# 5. Cloud Run v2 Service Deployment (Serverless Autoscaling - Gate 2 Compliance)
# ==============================================================================

resource "google_cloud_run_v2_service" "assessor_service" {
  name     = var.service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.adk_runtime_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = local.should_build ? "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}-repo/assessor:latest" : var.container_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_GENAI_USE_ENTERPRISE"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT_NUMBER"
        value = var.project_number
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = var.service_name
      }
      env {
        name  = "PRIMARY_MODEL_ID"
        value = "gemini-3.8-flash"
      }
      env {
        name  = "FALLBACK_MODEL_ID"
        value = "gemini-3.5-flash"
      }
      env {
        name  = "FAST_RAG_MODEL_ID"
        value = "gemini-3.5-flash-lite"
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis["run.googleapis.com"],
    google_project_service.enabled_apis["aiplatform.googleapis.com"],
    google_project_iam_member.adk_runtime_iam,
    terraform_data.serverless_container_build,
  ]
}

# Grant Cloud Run Invoker to Admin Principal & Runtime SA (Complies with Org Policy Domain Restricted Sharing)
resource "google_cloud_run_v2_service_iam_member" "authenticated_invoker" {
  for_each = {
    runtime_sa      = "serviceAccount:${google_service_account.adk_runtime_sa.email}"
    admin_principal = var.admin_principal
  }
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.assessor_service.name
  role     = "roles/run.invoker"
  member   = each.value
}
