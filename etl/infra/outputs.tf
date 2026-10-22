output "resource_group" {
  value = azurerm_resource_group.etl.name
}

output "eventhub_namespace" {
  description = "ETL_EVENTHUB_NAMESPACE for seeder.replay"
  value       = "${azurerm_eventhub_namespace.etl.name}.servicebus.windows.net"
}

output "servicebus_namespace" {
  value = "${azurerm_servicebus_namespace.etl.name}.servicebus.windows.net"
}

output "sql_server" {
  value = azurerm_mssql_server.etl.fully_qualified_domain_name
}

output "sql_database" {
  value = azapi_resource.database.name
}

output "graphql_url" {
  description = "Internal: reachable only from apps in this environment"
  value       = "https://${azurerm_container_app.dab.ingress[0].fqdn}/graphql"
}

output "stream_analytics_job" {
  value = azurerm_stream_analytics_job.etl.name
}

output "dab_identity_name" {
  description = "Database user name for the DAB managed identity"
  value       = azurerm_container_app.dab.name
}

output "window_seconds" {
  value = var.window_seconds
}

# Secrets: read with `terraform output -raw <name>`; never commit them.
output "eventhub_send_connection_string" {
  description = "ETL_EVENTHUB_CONNECTION_STRING for seeder.replay"
  value       = azurerm_eventhub_authorization_rule.seeder_send.primary_connection_string
  sensitive   = true
}

output "servicebus_listen_connection_string" {
  description = "For consumers of match-notifications"
  value       = azurerm_servicebus_topic_authorization_rule.consumers_listen.primary_connection_string
  sensitive   = true
}

output "registry" {
  description = "ETL registry for `az acr build` (admin.tf)"
  value       = azurerm_container_registry.etl.name
}

output "admin_url" {
  description = "Internal purge API base URL (POST /admin/matches/purge); null until admin_image_tag is set"
  value       = var.admin_image_tag == null ? null : "http://${azurerm_container_app.admin[0].ingress[0].fqdn}"
}

output "admin_host" {
  description = "The purge API's internal host, known before it exists (frontend ETL_ADMIN_UPSTREAM)"
  value       = "${var.name_prefix}-admin.internal.${azurerm_container_app_environment.etl.default_domain}"
}

output "admin_identity_name" {
  description = "Database user name for the purge API's managed identity; null until admin_image_tag is set"
  value       = var.admin_image_tag == null ? null : azurerm_container_app.admin[0].name
}

output "spadl_identity_name" {
  description = "Database user name for the SPADL post-processor's managed identity (spadl.tf); null until admin_image_tag is set"
  value       = var.admin_image_tag == null ? null : azurerm_container_app.spadl[0].name
}

output "admin_token" {
  description = "Bearer token for the purge API"
  value       = random_password.admin_token.result
  sensitive   = true
}

# For the stacks that share this environment and registry (narrative-engine, data-generation, terraform/).
output "container_app_environment_id" {
  value = azurerm_container_app_environment.etl.id
}

output "container_app_domain" {
  description = "Default domain; an app's internal address is <app>.internal.<domain>"
  value       = azurerm_container_app_environment.etl.default_domain
}

output "servicebus_namespace_id" {
  value = azurerm_servicebus_namespace.etl.id
}

output "dab_app_name" {
  value = azurerm_container_app.dab.name
}

output "registry_login_server" {
  value = azurerm_container_registry.etl.login_server
}

output "registry_username" {
  value = azurerm_container_registry.etl.admin_username
}

output "registry_password" {
  value     = azurerm_container_registry.etl.admin_password
  sensitive = true
}

output "eventhub_listen_connection_string" {
  description = "User backend: match-events, consumer group user-backend"
  value       = azurerm_eventhub_authorization_rule.user_backend_listen.primary_connection_string
  sensitive   = true
}
