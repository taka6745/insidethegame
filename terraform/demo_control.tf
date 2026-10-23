# The demo operator behind the frontend's public /demo-api/ (local/demo_control.py serve): starts the
# configured demo, cancels it, reports each stage's readiness from real checks. Internal ingress only;
# one replica kept warm; a /demo-api/status call wakes the apps it checks.
locals {
  demo_host = "${var.prefix}-demo.internal.${local.domain}"
  demo_env = {
    DEMO_FEED_URL    = "http://${local.feed.hls_origin_host}"
    DEMO_SEED_ROOT   = "/seeds"
    ETL_ADMIN_URL    = "http://${local.etl.admin_host}"
    ENGINE_ADMIN_URL = "http://${local.engine_host}"
    BACKEND_URL      = "http://${local.backend_host}"
    # Kept warm while a demo is live (the owners' health checks are always included): the ETL's data API and
    # this app itself, which otherwise scale to zero in a quiet spell mid-match.
    DEMO_KEEP_WARM_URLS = join(",", [replace(local.etl.graphql_url, "/graphql", "/health"), "http://${local.demo_host}/health"])
  }
  demo_secrets = {
    "etl-admin-token"    = { env = "ETL_ADMIN_TOKEN", value = local.etl.admin_token }
    "engine-admin-token" = { env = "ENGINE_ADMIN_TOKEN", value = local.narrative.admin_token }
  }
}

# Demo seeds (DEMO_SEEDS, demo build only) live on an Azure Files share mounted at /seeds, so they survive
# restarts and scale to zero.
resource "azurerm_storage_account" "seeds" {
  count                           = var.demo_seeds ? 1 : 0
  name                            = substr(replace("${local.name}seeds", "-", ""), 0, 24)
  resource_group_name             = azurerm_resource_group.app.name
  location                        = azurerm_resource_group.app.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = azurerm_resource_group.app.tags
}

resource "azurerm_storage_share" "seeds" {
  count              = var.demo_seeds ? 1 : 0
  name               = "seeds"
  storage_account_id = azurerm_storage_account.seeds[0].id
  quota              = 5 # GB
}

resource "azurerm_container_app_environment_storage" "seeds" {
  count                        = var.demo_seeds ? 1 : 0
  name                         = "${var.prefix}-seeds"
  container_app_environment_id = local.etl.container_app_environment_id
  account_name                 = azurerm_storage_account.seeds[0].name
  share_name                   = azurerm_storage_share.seeds[0].name
  access_key                   = azurerm_storage_account.seeds[0].primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app" "demo_control" {
  count                        = var.image_tag == null ? 0 : 1
  name                         = "${var.prefix}-demo"
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
    for_each = local.demo_secrets
    content {
      name  = secret.key
      value = secret.value.value
    }
  }

  dynamic "secret" {
    for_each = nonsensitive(var.stream_start_url != null) ? [1] : []
    content {
      name  = "stream-start-url"
      value = var.stream_start_url
    }
  }

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
    min_replicas = 1 # kept warm: a cold picker took ~40 s
    max_replicas = 1 # one operator: start and cancel are serialised in the process

    container {
      name  = "demo-control"
      image = "${local.etl.registry_login_server}/demo-control:${var.image_tag}"
      # Seeded starts parse and write three matches' seeds at once (CPU-bound JSON); 0.25 vCPU took 10 s at 60′.
      # Scales to zero, so the size costs only while it runs.
      cpu    = 1
      memory = "2Gi"

      dynamic "env" {
        for_each = local.demo_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.demo_secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }

      dynamic "env" {
        for_each = nonsensitive(var.stream_start_url != null) ? [1] : []
        content {
          name        = "DEMO_STREAM_START_URL"
          secret_name = "stream-start-url"
        }
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }

      dynamic "volume_mounts" {
        for_each = var.demo_seeds ? [1] : []
        content {
          name = "seeds"
          path = "/seeds"
        }
      }
    }

    dynamic "volume" {
      for_each = var.demo_seeds ? [1] : []
      content {
        name         = "seeds"
        storage_name = azurerm_container_app_environment_storage.seeds[0].name
        storage_type = "AzureFile"
      }
    }
  }
}
