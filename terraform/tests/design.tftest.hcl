# Mock provider: checks the intended resource graph WITHOUT credentials or Azure calls.
mock_provider "azurerm" {}

override_resource {
  target          = azurerm_servicebus_topic.topics["narratives"]
  override_during = plan
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/itgdemo-rg/providers/Microsoft.ServiceBus/namespaces/itgdemo-messages/topics/narratives"
  }
}

variables {
  subscription_id         = "00000000-0000-0000-0000-000000000000"
  database_admin_password = "Mock-Only-Password-42!"
}

run "service_boundaries" {
  command = plan

  assert {
    condition     = length(azurerm_postgresql_flexible_server_database.user) == 2
    error_message = "Keep accounts and matchapp as separate databases on the user server."
  }
  assert {
    condition     = azurerm_eventhub_consumer_group.consumers["etl"].name != azurerm_eventhub_consumer_group.consumers["user-backend"].name
    error_message = "ETL and user backend must receive independent copies of live events."
  }
  assert {
    condition     = azurerm_servicebus_subscription.consumers["user-backend"].topic_id == azurerm_servicebus_topic.topics["narratives"].id
    error_message = "User backend receives published narratives, not direct Cosmos reads."
  }
  assert {
    condition     = alltrue([for container in azurerm_cosmosdb_sql_container.memory : container.partition_key_paths == tolist(["/matchId"])])
    error_message = "Narrative storage must be partitioned by match."
  }
  assert {
    condition = (
      azurerm_cosmosdb_sql_container.stats.account_name == azurerm_cosmosdb_account.etl.name &&
      azurerm_cosmosdb_account.etl.name != azurerm_cosmosdb_account.narrative.name &&
      azurerm_cosmosdb_sql_container.stats.database_name == azurerm_cosmosdb_sql_database.etl.name &&
      azurerm_cosmosdb_sql_container.stats.partition_key_paths == tolist(["/matchId"])
    )
    error_message = "Standard stats belong in ETL-owned Cosmos storage, partitioned by match."
  }
  assert {
    condition = (
      !azurerm_cosmosdb_account.etl.public_network_access_enabled &&
      !azurerm_cosmosdb_account.narrative.public_network_access_enabled &&
      !azurerm_mssql_server.match.public_network_access_enabled &&
      !azurerm_postgresql_flexible_server.user.public_network_access_enabled
    )
    error_message = "Datastores must remain private; complete private connectivity before deploying."
  }
}
