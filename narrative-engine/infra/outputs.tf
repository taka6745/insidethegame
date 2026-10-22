output "resource_group" {
  value = azurerm_resource_group.narrative.name
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.narrative.endpoint
}

output "servicebus_namespace" {
  value = data.terraform_remote_state.etl.outputs.servicebus_namespace
}

# Secrets: read with `terraform output -raw <name>`; never commit them.
output "narratives_send_connection_string" {
  description = "Engine -> narratives topic"
  value       = azurerm_servicebus_topic_authorization_rule.narratives_send.primary_connection_string
  sensitive   = true
}

output "narratives_listen_connection_string" {
  description = "User backend (and our checks) <- narratives topic"
  value       = azurerm_servicebus_topic_authorization_rule.narratives_listen.primary_connection_string
  sensitive   = true
}

output "registry_name" {
  value = azurerm_container_registry.engine.name
}

output "foundry_endpoint" {
  value = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.openai.azure.com/openai/v1"
}

output "agent_models" {
  description = "Model and reasoning effort per agent"
  value       = var.agents
}

output "foundry_key" {
  description = "For local runs against Foundry (OPENAI_API_KEY with OPENAI_BASE_URL = foundry_endpoint)"
  value       = azurerm_cognitive_account.foundry.primary_access_key
  sensitive   = true
}

output "engine_graphql_url" {
  value = length(azurerm_container_app.engine) > 0 ? "https://${azurerm_container_app.engine[0].ingress[0].fqdn}/graphql" : null
}

output "foundry_account_id" {
  description = "Other stacks add their own deployments to this account (terraform/: question agents)"
  value       = azurerm_cognitive_account.foundry.id
}

output "engine_app_name" {
  value = "${var.name_prefix}-engine"
}

output "admin_token" {
  description = "Bearer token for the engine's purge (frontend /purge-api/engine)"
  value       = random_password.admin_token.result
  sensitive   = true
}

output "decision" {
  description = "Microsoft-Decision-1 on this Foundry account (SystemOne API), for the backend's follow check; key = foundry_key"
  value = {
    base_url = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.cognitiveservices.azure.com"
    model    = azurerm_cognitive_deployment.model[var.decision.deployment].name
  }
}
