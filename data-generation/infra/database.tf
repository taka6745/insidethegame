# The provider's own Postgres (runs, catalogue, tombstones). Burstable B1ms: the cheapest server.
# Public endpoint limited to Azure services (the shared environment has no VNet), TLS required.
resource "random_password" "database" {
  length      = 32
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

resource "azurerm_postgresql_flexible_server" "feed" {
  name                          = "${local.name}-pg"
  resource_group_name           = azurerm_resource_group.feed.name
  location                      = azurerm_resource_group.feed.location
  version                       = "16"
  administrator_login           = "feedadmin"
  administrator_password        = random_password.database.result
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  public_network_access_enabled = true
  tags                          = local.tags

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.feed.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "feed" {
  name      = "feed"
  server_id = azurerm_postgresql_flexible_server.feed.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
