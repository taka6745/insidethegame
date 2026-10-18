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
  value = "https://${azurerm_container_app.dab.ingress[0].fqdn}/graphql"
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
