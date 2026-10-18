output "eventhub_name" { value = azurerm_eventhub.match.name }
output "servicebus_topics" { value = sort(keys(azurerm_servicebus_topic.topics)) }
output "user_databases" { value = sort(keys(azurerm_postgresql_flexible_server_database.user)) }
output "narrative_containers" { value = sort(keys(azurerm_cosmosdb_sql_container.memory)) }
output "container_environment_id" { value = azurerm_container_app_environment.app.id }
output "etl_stats_container" { value = azurerm_cosmosdb_sql_container.stats.name }
