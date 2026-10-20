# Microsoft Foundry (AI Services account) with pay-per-token deployments. Each agent picks one of
# them and a reasoning effort in var.agents, so moving the author to a stronger model is: add it to
# var.models, point agents.author at it, apply.
# Key auth because this account (Contributor) cannot grant the app a Cognitive Services role.
# LATER: managed identity with "Cognitive Services OpenAI User", then local_auth_enabled = false.
resource "azurerm_cognitive_account" "foundry" {
  name                  = "${local.name}-foundry"
  location              = azurerm_resource_group.narrative.location
  resource_group_name   = azurerm_resource_group.narrative.name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = "${local.name}-foundry"
  local_auth_enabled    = true
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "model" {
  for_each             = var.models
  name                 = each.key
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = each.value.format
    name    = each.key
    version = each.value.version
  }

  sku {
    name     = each.value.sku
    capacity = each.value.capacity
  }
}

moved {
  from = azurerm_cognitive_deployment.model
  to   = azurerm_cognitive_deployment.model["gpt-5-mini"]
}
