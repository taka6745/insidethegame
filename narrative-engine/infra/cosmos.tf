# Serverless: billed per request, nothing while idle. Entra ID only (no keys): Cosmos data-plane
# role assignments are Cosmos resources, which a Contributor can create.
resource "azurerm_cosmosdb_account" "narrative" {
  name                         = "${local.name}-cosmos"
  location                     = azurerm_resource_group.narrative.location
  resource_group_name          = azurerm_resource_group.narrative.name
  offer_type                   = "Standard"
  kind                         = "GlobalDocumentDB"
  local_authentication_enabled = false
  tags                         = local.tags

  capabilities {
    name = "EnableServerless"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.narrative.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "narrative" {
  name                = "narrative"
  resource_group_name = azurerm_resource_group.narrative.name
  account_name        = azurerm_cosmosdb_account.narrative.name
}

# All partitioned by matchId (docs/design/narrative-generation-engine.md section 8); analyses are
# immutable storyline snapshots, storylines their current projection; subscriptionDecisions are the
# immutable story-follow decisions, subscriptionNarratives the follow narratives. A purge deletes all but
# the tombstones.
resource "azurerm_cosmosdb_sql_container" "containers" {
  for_each = toset(["checkpoints", "contextBlocks", "narratives", "analyses", "storylines", "subscriptionDecisions",
  "subscriptionNarratives", "tombstones"])
  name                  = each.key
  resource_group_name   = azurerm_resource_group.narrative.name
  account_name          = azurerm_cosmosdb_account.narrative.name
  database_name         = azurerm_cosmosdb_sql_database.narrative.name
  partition_key_paths   = ["/matchId"]
  partition_key_version = 2
}

# You, for local runs and tests (DefaultAzureCredential via `az login`). The engine's identity: app.tf.
resource "azurerm_cosmosdb_sql_role_assignment" "me" {
  resource_group_name = azurerm_resource_group.narrative.name
  account_name        = azurerm_cosmosdb_account.narrative.name
  role_definition_id  = "${azurerm_cosmosdb_account.narrative.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002" # Data Contributor
  principal_id        = local.me
  scope               = azurerm_cosmosdb_account.narrative.id
}
