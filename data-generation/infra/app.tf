locals {
  feed_secrets = {
    "database-url" = { env = "FEED_DATABASE_URL", value = "postgresql://feedadmin:${random_password.database.result}@${azurerm_postgresql_flexible_server.feed.fqdn}:5432/feed?sslmode=require" }
    "eventhub"     = { env = "FEED_EVENTHUB_CONNECTION_STRING", value = local.etl.eventhub_send_connection_string }
    "blob"         = { env = "FEED_BLOB_CONNECTION_STRING", value = azurerm_storage_account.feed.primary_connection_string }
  }
}

# One replica: runs live in the process (they resume from the database after a restart).
# Internal ingress: our nginx (/media/hls/) and backend (FEED_HLS_BASE) reach the HLS origin inside
# the environment; the dev-only admin API is not on the internet.
resource "azurerm_container_app" "feed" {
  count                        = var.image_tag == null ? 0 : 1
  name                         = "${var.name_prefix}-app"
  container_app_environment_id = local.etl.container_app_environment_id
  resource_group_name          = azurerm_resource_group.feed.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  registry {
    server               = local.etl.registry_login_server
    username             = local.etl.registry_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = local.etl.registry_password
  }

  dynamic "secret" {
    for_each = local.feed_secrets
    content {
      name  = secret.key
      value = secret.value.value
    }
  }

  ingress {
    external_enabled           = false
    allow_insecure_connections = true # plain HTTP inside the environment
    target_port                = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = 1

    container {
      name   = "feed"
      image  = "${local.etl.registry_login_server}/feed:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.feed_secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }
      env {
        name  = "FEED_EVENTHUB_NAME"
        value = "match-events"
      }
      env {
        name  = "FEED_ALLOW_SEEK"
        value = "0"
      }
      env {
        name  = "DEMO_SEEDS"
        value = var.demo_seeds ? "1" : "0"
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 8000
      }
    }
  }
}
