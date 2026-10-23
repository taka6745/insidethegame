# Entra-only auth: you are the admin; Stream Analytics and DAB connect with managed identities.
# Schema and identity grants are applied after `terraform apply` by `python -m devtools azure-setup`.
resource "azurerm_mssql_server" "etl" {
  name                          = "${local.name}-sql"
  location                      = azurerm_resource_group.etl.location
  resource_group_name           = azurerm_resource_group.etl.name
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true
  tags                          = local.tags

  azuread_administrator {
    login_username              = "etl-admin"
    object_id                   = local.me
    azuread_authentication_only = true
  }
}

# Lets Azure services (Stream Analytics, Container Apps) reach the server.
resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.etl.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_mssql_firewall_rule" "me" {
  name             = "DeveloperIp"
  server_id        = azurerm_mssql_server.etl.id
  start_ip_address = local.my_ip
  end_ip_address   = local.my_ip
}

# azurerm does not expose the free offer, so the database is created through azapi.
# Free offer: 100,000 vCore-seconds and 32 GB per month. Past it the database bills (sql_after_free_limit), so a
# busy demo month never pauses it; idle, it auto-pauses after an hour and resumes on the next login (~1 min).
resource "azapi_resource" "database" {
  type      = "Microsoft.Sql/servers/databases@2023-08-01"
  name      = "insidethegame"
  parent_id = azurerm_mssql_server.etl.id
  location  = azurerm_resource_group.etl.location
  tags      = local.tags

  body = {
    sku = { name = "GP_S_Gen5", tier = "GeneralPurpose", family = "Gen5", capacity = 2 }
    properties = {
      useFreeLimit                     = true
      freeLimitExhaustionBehavior      = var.sql_after_free_limit
      autoPauseDelay                   = 60
      minCapacity                      = 0.5
      maxSizeBytes                     = 34359738368
      requestedBackupStorageRedundancy = "Local"
    }
  }
}
