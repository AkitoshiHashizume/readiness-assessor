variable "project_id" {
  description = "Google Cloud Project ID for AI Architecture Readiness Assessor"
  type        = string
  default     = "ai-readiness-assessor"
}

variable "project_number" {
  description = "Google Cloud Project Number"
  type        = string
  default     = "123456789012"
}

variable "region" {
  description = "Google Cloud Region for Cloud Run and Vertex AI"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run Service Name"
  type        = string
  default     = "ai-readiness-assessor"
}

variable "service_account_id" {
  description = "Service Account ID for the Cloud Run runtime identity"
  type        = string
  default     = "assessor-runtime-sa"
}

variable "container_image" {
  description = "Container image to deploy to Cloud Run (defaults to public Cloud Run hello image for initial apply before custom image push)"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "admin_principal" {
  description = "Organization principal account authorized to invoke Cloud Run and Vertex AI endpoints"
  type        = string
  default     = "user:lead-reviewer@example.com"
}

variable "trigger_cloud_build" {
  description = "If true, Terraform triggers a serverless Google Cloud Build via gcloud builds submit and deploys the built image to Cloud Run"
  type        = bool
  default     = false
}

