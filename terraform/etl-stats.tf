# ETL owns standard statistics. Consumers read its GraphQL API, not this account.
resource "azurerm_cosmosdb_account" "etl" {
  name                          = "${var.prefix}-etl"
  location                      = azurerm_resource_group.app.location
  resource_group_name           = azurerm_resource_group.app.name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  public_network_access_enabled = false
  consistency_policy { consistency_level = "Session" }
  geo_location {
    location          = azurerm_resource_group.app.location
    failover_priority = 0
  }
  capabilities { name = "EnableServerless" }
}

resource "azurerm_cosmosdb_sql_database" "etl" {
  name                = "etl"
  resource_group_name = azurerm_resource_group.app.name
  account_name        = azurerm_cosmosdb_account.etl.name
}

resource "azurerm_cosmosdb_sql_container" "stats" {
  name                = "standardStats"
  resource_group_name = azurerm_resource_group.app.name
  account_name        = azurerm_cosmosdb_account.etl.name
  database_name       = azurerm_cosmosdb_sql_database.etl.name
  partition_key_paths = ["/matchId"]
}
