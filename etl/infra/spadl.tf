# SPADL post-processor on Azure: the etl-stream image with ETL_ROLE=spadl converts committed MA3 rows into
# dbo.spadlActions (spadl/worker.py); locally the same code runs as a thread in etl-stream. It polls SQL, so it
# keeps one replica and needs no ingress. After ETL_SPADL_IDLE_SECONDS without work it closes its SQL connection
# and polls only the hub's partition properties until a feed sends again, so serverless SQL can auto-pause.
# Deployed with the purge API (same image tag); `python -m devtools azure-setup` grants its database user.
resource "azurerm_container_app" "spadl" {
  count                        = var.admin_image_tag == null ? 0 : 1
  name                         = "${var.name_prefix}-spadl"
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
    name  = "eventhub-listen"
    value = azurerm_eventhub_authorization_rule.spadl_listen.primary_connection_string
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "spadl"
      image  = "${azurerm_container_registry.etl.login_server}/etl-stream:${var.admin_image_tag}"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "ETL_ROLE"
        value = "spadl"
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
        name        = "ETL_EVENTHUB_CONNECTION_STRING"
        secret_name = "eventhub-listen"
      }
      env {
        name  = "ETL_EVENTHUB_NAME"
        value = azurerm_eventhub.match_events.name
      }
      env {
        name  = "ETL_SPADL_IDLE_SECONDS"
        value = "300"
      }
    }
  }
}
