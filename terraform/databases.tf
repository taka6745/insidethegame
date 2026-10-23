# User backend only. ETL SQL lives in etl/infra; narrative Cosmos DB in narrative-engine/infra.
# Public endpoint limited to Azure services, TLS required: the shared Container Apps environment has
# no VNet, so a private endpoint would be unreachable. The backend logs in as this server admin
# (terraform/docs/decisions.md: production gaps).
resource "random_password" "database" {
  length      = 32
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

resource "azurerm_postgresql_flexible_server" "user" {
  name                          = "${local.name}-user"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "16"
  administrator_login           = "itgadmin"
  administrator_password        = random_password.database.result
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  public_network_access_enabled = true

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.user.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "user" {
  for_each  = toset(["accounts", "matchapp"])
  name      = each.value
  server_id = azurerm_postgresql_flexible_server.user.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
