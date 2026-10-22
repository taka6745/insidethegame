# Purge API on Azure: the etl-stream image (local_stream) with ETL_ROLE=admin serves only
# POST /admin/matches/purge against Azure SQL; Stream Analytics replaces its worker. Two-step deploy:
# apply (registry), `az acr build --registry <etl_registry> --image etl-stream:TAG ../`, then apply with
# -var admin_image_tag=TAG, then `python -m devtools azure-setup` to grant the app's database user.

# Basic registry; the app pulls with the admin credentials because this account cannot grant AcrPull.
# LATER: managed identity with AcrPull, admin_enabled = false.
resource "azurerm_container_registry" "etl" {
  name                = replace("${local.name}acr", "-", "")
  location            = azurerm_resource_group.etl.location
  resource_group_name = azurerm_resource_group.etl.name
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.tags
}

# Bearer token for the purge (`terraform output -raw admin_token`).
resource "random_password" "admin_token" {
  length  = 40
  special = false
}

resource "azurerm_container_app" "admin" {
  count                        = var.admin_image_tag == null ? 0 : 1
  name                         = "${var.name_prefix}-admin"
  container_app_environment_id = azurerm_container_app_environment.etl.id
  resource_group_name          = azurerm_resource_group.etl.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type = "SystemAssigned"
  }

  registry {
    server               = azurerm_container_registry.etl.login_server
    username             = azurerm_container_registry.etl.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.etl.admin_password
  }

  secret {
    name  = "admin-token"
    value = random_password.admin_token.result
  }

  # Internal only (the frontend's /purge-api/etl adds the token); plain HTTP inside the environment.
  ingress {
    external_enabled           = false
    allow_insecure_connections = true
    target_port                = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name  = "admin"
      image = "${azurerm_container_registry.etl.login_server}/etl-stream:${var.admin_image_tag}"
      # Seeded starts parse and write three matches' seeds at once (CPU-bound JSON); 0.25 vCPU took 10 s at 60′.
      # Scales to zero, so the size costs only while it runs.
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "ETL_ROLE"
        value = "admin"
      }
      env {
        name  = "DEMO_SEEDS"
        value = var.demo_seeds ? "1" : "0"
      }
      env {
        name  = "ETL_SQL_AUTH"
        value = "managed-identity"
      }
      env {
        name  = "ETL_SQL_HOST"
        value = azurerm_mssql_server.etl.fully_qualified_domain_name
      }
      env {
        name  = "ETL_SQL_DATABASE"
        value = azapi_resource.database.name
      }
      env {
        name        = "ETL_ADMIN_TOKEN"
        secret_name = "admin-token"
      }
    }
  }
}
