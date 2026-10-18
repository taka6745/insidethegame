resource "azurerm_resource_group" "app" {
  name     = "${var.prefix}-rg"
  location = var.location
  tags     = { project = "InsideTheGame", environment = "hackathon" }
}

resource "azurerm_log_analytics_workspace" "app" {
  name                = "${var.prefix}-logs"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "app" {
  name                       = "${var.prefix}-apps"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
}

# Container Apps are added when real application images exist. No placeholder apps.
# The ETL service owns the Stream Analytics job, query, inputs, outputs and event-time policy.
