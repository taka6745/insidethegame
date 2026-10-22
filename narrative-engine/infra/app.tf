# The engine on Container Apps. Two-step deploy: apply (registry, environment, Foundry), then
# `python -m narrative_engine.devtools.azure build --tag X`, then apply with -var engine_image_tag=X.

# Basic registry; the app pulls with the admin credentials because this account cannot grant
# AcrPull. LATER: managed identity with AcrPull, admin_enabled = false.
resource "azurerm_container_registry" "engine" {
  name                = replace("${local.name}acr", "-", "")
  location            = azurerm_resource_group.narrative.location
  resource_group_name = azurerm_resource_group.narrative.name
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.tags
}

# Bearer token for POST /admin/matches/purge.
resource "random_password" "admin_token" {
  length  = 40
  special = false
}

locals {
  etl = data.terraform_remote_state.etl.outputs
  # Secrets (Container Apps secret names) -> environment variables.
  engine_secrets = {
    "sb-notifications" = { env = "SERVICEBUS_NOTIFICATIONS", value = local.etl.servicebus_listen_connection_string }
    "sb-narratives"    = { env = "SERVICEBUS_NARRATIVES", value = azurerm_servicebus_topic_authorization_rule.narratives_send.primary_connection_string }
    "foundry-key"      = { env = "OPENAI_API_KEY", value = azurerm_cognitive_account.foundry.primary_access_key }
    "decision-key"     = { env = "DECISION_API_KEY", value = azurerm_cognitive_account.foundry.primary_access_key }
    "appinsights"      = { env = "APPLICATIONINSIGHTS_CONNECTION_STRING", value = azurerm_application_insights.engine.connection_string }
    "admin-token"      = { env = "ADMIN_TOKEN", value = random_password.admin_token.result }
  }
  # OPENAI_MODEL_<ROLE> and OPENAI_EFFORT_<ROLE> per agent (see narrative_engine/agents/llm.py).
  agent_env = merge([for role, agent in var.agents : merge(
    { "OPENAI_MODEL_${upper(role)}" = azurerm_cognitive_deployment.model[agent.model].name },
  agent.effort == null ? {} : { "OPENAI_EFFORT_${upper(role)}" = agent.effort })]...)
  engine_env = merge({
    ETL_GRAPHQL_URL   = local.etl.graphql_url
    COSMOS_ENDPOINT   = azurerm_cosmosdb_account.narrative.endpoint
    OPENAI_BASE_URL   = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.openai.azure.com/openai/v1"
    OTEL_SERVICE_NAME = "narrative-engine"
    PORT              = "8000"
    USER_BACKEND_URL  = var.user_backend_url
    # Microsoft-Decision-1 on the same Foundry account, over the SystemOne API.
    DECISION_PROVIDER      = "systemone"
    DECISION_BASE_URL      = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.cognitiveservices.azure.com"
    DECISION_MODEL         = azurerm_cognitive_deployment.model[var.decision.deployment].name
    DECISION_MAX_QUESTIONS = tostring(var.decision.max_questions)
    # Paced to the deployment's capacity (requests per minute), shared by every match.
    DECISION_REQUESTS_PER_MINUTE = tostring(var.models[var.decision.deployment].capacity)
    DECISION_RETRIES             = "4"
    DEMO_SEEDS                   = var.demo_seeds ? "1" : "0"
  }, local.agent_env)
}

# One replica: each match's worker lives in memory, so a second replica would race it.
resource "azurerm_container_app" "engine" {
  count                        = var.engine_image_tag == null ? 0 : 1
  name                         = "${var.name_prefix}-engine"
  container_app_environment_id = local.etl.container_app_environment_id # trial: one environment per region, the ETL's
  resource_group_name          = azurerm_resource_group.narrative.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption" # the ETL environment's default profile
  tags                         = local.tags

  identity {
    type = "SystemAssigned"
  }

  registry {
    server               = azurerm_container_registry.engine.login_server
    username             = azurerm_container_registry.engine.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.engine.admin_password
  }

  dynamic "secret" {
    for_each = local.engine_secrets
    content {
      name  = secret.key
      value = secret.value.value
    }
  }

  # Internal only: the user backend reads GraphQL and the frontend's /purge-api/engine (dev consoles)
  # calls the purge, which also needs the bearer token. Plain HTTP stays inside the environment.
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
      name   = "engine"
      image  = "${azurerm_container_registry.engine.login_server}/narrative-engine:${var.engine_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.engine_secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }

      dynamic "env" {
        for_each = local.engine_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.user_backend_url != null
      error_message = "Set user_backend_url: the engine reads audience targets and prompts from the user backend."
    }
  }
}

resource "azurerm_cosmosdb_sql_role_assignment" "engine" {
  count               = length(azurerm_container_app.engine)
  resource_group_name = azurerm_resource_group.narrative.name
  account_name        = azurerm_cosmosdb_account.narrative.name
  role_definition_id  = "${azurerm_cosmosdb_account.narrative.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002" # Data Contributor
  principal_id        = azurerm_container_app.engine[0].identity[0].principal_id
  scope               = azurerm_cosmosdb_account.narrative.id
}
