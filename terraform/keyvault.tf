# The backend's secrets, read by its user-assigned managed identity. Access policies, not RBAC: this
# account (Contributor) cannot create role assignments.
resource "azurerm_user_assigned_identity" "backend" {
  name                = "${var.prefix}-backend-id"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
}

resource "azurerm_key_vault" "app" {
  name                       = "${local.name}-kv"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # `./dev azure down` purges it so names stay reusable
  rbac_authorization_enabled = false # access policies
}

resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id       = azurerm_key_vault.app.id
  tenant_id          = data.azurerm_client_config.current.tenant_id
  object_id          = data.azurerm_client_config.current.object_id
  secret_permissions = ["Get", "List", "Set", "Delete", "Purge", "Recover"]
}

resource "azurerm_key_vault_access_policy" "backend" {
  key_vault_id       = azurerm_key_vault.app.id
  tenant_id          = data.azurerm_client_config.current.tenant_id
  object_id          = azurerm_user_assigned_identity.backend.principal_id
  secret_permissions = ["Get"]
}

locals {
  database_base = "postgresql://itgadmin:${random_password.database.result}@${azurerm_postgresql_flexible_server.user.fqdn}:5432"
  # Key Vault secret name -> backend environment variable.
  backend_secret_env = {
    "accounts-database-url" = "ACCOUNTS_DATABASE_URL"
    "matchapp-database-url" = "MATCH_APP_DATABASE_URL"
    "match-eventhub"        = "MATCH_EVENTHUB_CONNECTION_STRING"
    "narratives-servicebus" = "NARRATIVE_SERVICEBUS_CONNECTION_STRING"
    "foundry-key"           = "LOCAL_LLM_API_KEY"
    "decision-key"          = "DECISION_API_KEY" # same Foundry account key; the adapter takes a key or a static bearer
  }
  backend_secret_values = {
    "accounts-database-url" = "${local.database_base}/accounts?sslmode=require"
    "matchapp-database-url" = "${local.database_base}/matchapp?sslmode=require"
    "match-eventhub"        = local.etl.eventhub_listen_connection_string
    "narratives-servicebus" = local.narrative.narratives_listen_connection_string
    "foundry-key"           = local.narrative.foundry_key
    "decision-key"          = local.narrative.foundry_key
  }
}

resource "azurerm_key_vault_secret" "backend" {
  for_each     = local.backend_secret_env
  name         = each.key
  value        = local.backend_secret_values[each.key]
  key_vault_id = azurerm_key_vault.app.id
  depends_on   = [azurerm_key_vault_access_policy.deployer]
}
