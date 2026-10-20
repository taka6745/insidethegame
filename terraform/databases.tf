resource "azurerm_mssql_server" "match" {
  name                          = "${var.prefix}-match"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "12.0"
  administrator_login           = "itgadmin"
  administrator_login_password  = var.database_admin_password
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
}

resource "azurerm_mssql_database" "match" {
  name                        = "matchdata"
  server_id                   = azurerm_mssql_server.match.id
  sku_name                    = "GP_S_Gen5_1"
  min_capacity                = 0.5
  auto_pause_delay_in_minutes = 60
  max_size_gb                 = 5
}

resource "azurerm_cosmosdb_account" "narrative" {
  name                          = "${var.prefix}-narrative"
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

resource "azurerm_cosmosdb_sql_database" "narrative" {
  name                = "narrative"
  resource_group_name = azurerm_resource_group.app.name
  account_name        = azurerm_cosmosdb_account.narrative.name
}

resource "azurerm_cosmosdb_sql_container" "memory" {
  for_each            = toset(["contextBlocks", "narratives", "checkpoints"])
  name                = each.value
  resource_group_name = azurerm_resource_group.app.name
  account_name        = azurerm_cosmosdb_account.narrative.name
  database_name       = azurerm_cosmosdb_sql_database.narrative.name
  partition_key_paths = ["/matchId"]
}

resource "azurerm_postgresql_flexible_server" "user" {
  name                          = "${var.prefix}-user"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "16"
  administrator_login           = "itgadmin"
  administrator_password        = var.database_admin_password
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  public_network_access_enabled = false
}

resource "azurerm_postgresql_flexible_server_database" "user" {
  for_each  = toset(["accounts", "matchapp"])
  name      = each.value
  server_id = azurerm_postgresql_flexible_server.user.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
