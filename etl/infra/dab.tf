# The shared DAB config with GraphQL introspection off: the deployed clients send only fixed queries.
locals {
  dab_config = jsondecode(file("${path.module}/../dab/dab-config.json"))
  dab_config_deployed = jsonencode(merge(local.dab_config, { runtime = merge(local.dab_config.runtime, {
    graphql = merge(local.dab_config.runtime.graphql, { "allow-introspection" = false })
  }) }))
}

resource "azurerm_log_analytics_workspace" "etl" {
  name                = "${local.name}-logs"
  location            = azurerm_resource_group.etl.location
  resource_group_name = azurerm_resource_group.etl.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5
  tags                = local.tags
}

resource "azurerm_container_app_environment" "etl" {
  name                       = "${local.name}-cae"
  location                   = azurerm_resource_group.etl.location
  resource_group_name        = azurerm_resource_group.etl.name
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.etl.id
  tags                       = local.tags
}

# Data API builder from Microsoft's public image; the config is mounted from a secret, so no registry is needed.
# The GraphQL is anonymous read, so it is never on the internet.
resource "azurerm_container_app" "dab" {
  name                         = "${var.name_prefix}-dab"
  container_app_environment_id = azurerm_container_app_environment.etl.id
  resource_group_name          = azurerm_resource_group.etl.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type = "SystemAssigned"
  }

  secret {
    name  = "dab-config"
    value = local.dab_config_deployed
  }

  # Internal only: the user backend and the narrative engine share this environment.
  ingress {
    external_enabled = false
    target_port      = 5000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "dab"
      image  = var.dab_image
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["--ConfigFileName", "/App/config/dab-config"]

      env {
        name  = "DATABASE_CONNECTION_STRING"
        value = "Server=tcp:${azurerm_mssql_server.etl.fully_qualified_domain_name},1433;Database=${azapi_resource.database.name};Authentication=Active Directory Managed Identity;Encrypt=True;"
      }

      volume_mounts {
        name = "config"
        path = "/App/config"
      }
    }

    volume {
      name         = "config"
      storage_type = "Secret"
    }
  }
}
