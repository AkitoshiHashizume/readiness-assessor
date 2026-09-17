output "project_id" {
  description = "Configured Google Cloud Project ID"
  value       = var.project_id
}

output "service_account_email" {
  description = "Email of the least-privilege ADK Runtime Service Account"
  value       = google_service_account.adk_runtime_sa.email
}

output "artifact_registry_repo_url" {
  description = "Artifact Registry Docker repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.assessor_repo.repository_id}"
}

output "cloud_run_service_url" {
  description = "Public HTTPS URL of the deployed Cloud Run AI Architecture Readiness Assessment Agent"
  value       = google_cloud_run_v2_service.assessor_service.uri
}
