# Developer consoles (/dev/, /feed-api/, /purge-api/, /dev-api/, /api/) behind HTTP basic auth
# (user `dev`). With dev_admin = false they are off entirely.
resource "random_password" "dev_admin" {
  count   = var.dev_admin ? 1 : 0
  length  = 24
  special = false
}

locals {
  frontend_env = {
    BACKEND_UPSTREAM      = local.backend_host
    MEDIA_ORIGIN          = local.feed.hls_origin_host
    FEED_ADMIN_UPSTREAM   = local.feed.hls_origin_host
    DEMO_CONTROL_UPSTREAM = local.demo_host
    ETL_ADMIN_UPSTREAM    = local.etl.admin_host
    ENGINE_ADMIN_UPSTREAM = local.engine_host
    NGINX_RESOLVER        = "auto" # the environment's DNS, from /etc/resolv.conf
    ENABLE_DEV_ADMIN      = var.dev_admin ? "1" : "0"
  }
  # Dev consoles only: Container Apps secret -> env. nginx adds each owner's bearer token to its
  # /purge-api/ call (tools/nginx-setup.envsh); the browser never sees them.
  # Keys stay non-sensitive so they can drive for_each; values are looked up.
  frontend_secret_env = var.dev_admin ? {
    "dev-admin-password" = "DEV_ADMIN_PASSWORD"
    "etl-admin-token"    = "ETL_ADMIN_TOKEN"
    "engine-admin-token" = "ENGINE_ADMIN_TOKEN"
  } : {}
  frontend_secret_values = var.dev_admin ? {
    "dev-admin-password" = random_password.dev_admin[0].result
    "etl-admin-token"    = local.etl.admin_token
    "engine-admin-token" = local.narrative.admin_token
  } : {}
}

# Public entry point: static viewer, /viewer-api/ -> backend, /media/hls/ -> the feed's HLS origin.
# Stateless, so it scales to zero.
resource "azurerm_container_app" "frontend" {
  count                        = var.image_tag == null ? 0 : 1
  name                         = "${var.prefix}-web"
  container_app_environment_id = local.etl.container_app_environment_id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

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
    for_each = local.frontend_secret_env
    content {
      name  = secret.key
      value = local.frontend_secret_values[secret.key]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 80
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "frontend"
      image  = "${local.etl.registry_login_server}/frontend:${var.image_tag}"
      cpu    = 0.25
      memory = "0.5Gi"

      dynamic "env" {
        for_each = local.frontend_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.frontend_secret_env
        content {
          name        = env.value
          secret_name = env.key
        }
      }
    }
  }
}
