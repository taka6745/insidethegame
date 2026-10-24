locals {
  backend_env = {
    ETL_GRAPHQL_URL                   = local.etl.graphql_url
    NARRATIVE_GRAPHQL_URL             = local.narrative_url
    FEED_HLS_BASE                     = local.feed.hls_base_url
    MATCH_EVENTHUB_NAME               = "match-events"
    MATCH_EVENTHUB_CONSUMER_GROUP     = "user-backend"
    NARRATIVE_SERVICEBUS_TOPIC        = "narratives"
    NARRATIVE_SERVICEBUS_SUBSCRIPTION = "user-backend"
    LOCAL_LLM_BASE_URL                = local.narrative.foundry_endpoint # Azure OpenAI v1 (OpenAI-compatible)
    LOCAL_LLM_MODEL                   = azurerm_cognitive_deployment.questions.name
    LOCAL_LLM_EFFORT                  = var.question_model.effort == null ? "" : var.question_model.effort
    DECISION_BASE_URL                 = local.narrative.decision.base_url # "Follow this story?": the engine's Decision-1
    DECISION_MODEL                    = local.narrative.decision.model
    QUESTION_TIMEOUT_SECONDS          = tostring(var.question_timeout_seconds)
    ENABLE_DEV_FEED                   = var.dev_admin ? "1" : "0" # internal ingress; nginx gates /dev-api/
    ENABLE_FILTER_LAB                 = var.dev_admin ? "1" : "0"
    DEMO_SEEDS                        = var.demo_seeds ? "1" : "0"
  }
}

# One replica: match ownership, projections and fan-out are process-local. Always on: it consumes
# Event Hubs. Internal ingress: only the frontend's nginx and the engine call it.
resource "azurerm_container_app" "backend" {
  count                        = var.image_tag == null ? 0 : 1
  name                         = "${var.prefix}-backend"
  container_app_environment_id = local.etl.container_app_environment_id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.backend.id]
  }

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
    for_each = local.backend_secret_env
    content {
      name                = secret.key
      key_vault_secret_id = azurerm_key_vault_secret.backend[secret.key].versionless_id
      identity            = azurerm_user_assigned_identity.backend.id
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
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "backend"
      image  = "${local.etl.registry_login_server}/user-backend:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.backend_secret_env
        content {
          name        = env.value
          secret_name = env.key
        }
      }

      dynamic "env" {
        for_each = local.backend_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # /ready is 503 until the database answers and a model is configured (upstreams and model reachability
      # are not checked: /dev/pipeline shows them). It gates traffic; the TCP liveness probe never restarts on it.
      readiness_probe {
        transport = "HTTP"
        path      = "/ready"
        port      = 8000
      }
      liveness_probe {
        transport = "TCP"
        port      = 8000
      }
    }
  }

  depends_on = [azurerm_key_vault_access_policy.backend]

  lifecycle {
    precondition {
      condition     = try(local.feed.hls_base_url, null) != null
      error_message = "Apply data-generation/infra first: the backend reads the feed's HLS origin."
    }
  }
}
