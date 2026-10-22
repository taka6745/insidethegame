# Mock provider: checks the intended resource graph WITHOUT credentials or Azure calls.
mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = { tenant_id = "00000000-0000-0000-0000-000000000001", object_id = "00000000-0000-0000-0000-000000000002" }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = { principal_id = "00000000-0000-0000-0000-000000000003" }
  }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  image_tag       = "test"
}

override_data {
  target = data.terraform_remote_state.etl
  values = {
    outputs = {
      container_app_environment_id      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/cae"
      container_app_domain              = "example.australiaeast.azurecontainerapps.io"
      registry_login_server             = "registry.azurecr.io"
      registry_username                 = "registry"
      registry_password                 = "mock"
      graphql_url                       = "https://dab.example/graphql"
      admin_host                        = "itg-etl-dev-admin.internal.example.australiaeast.azurecontainerapps.io"
      admin_token                       = "mock-etl-token"
      eventhub_listen_connection_string = "Endpoint=sb://mock/;SharedAccessKeyName=user-backend-listen;SharedAccessKey=mock;EntityPath=match-events"
    }
  }
}

override_data {
  target = data.terraform_remote_state.narrative
  values = {
    outputs = {
      engine_app_name                     = "itg-narrative-dev-engine"
      foundry_account_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/foundry"
      foundry_endpoint                    = "https://foundry.openai.azure.com/openai/v1"
      foundry_key                         = "mock"
      decision                            = { base_url = "https://foundry.cognitiveservices.azure.com", model = "decision-1" }
      admin_token                         = "mock-engine-token"
      narratives_listen_connection_string = "Endpoint=sb://mock/;SharedAccessKeyName=consumers-listen;SharedAccessKey=mock;EntityPath=narratives"
    }
  }
}

override_data {
  target = data.terraform_remote_state.feed
  values = {
    outputs = {
      hls_origin_host = "itg-feed-dev-app.internal.example.australiaeast.azurecontainerapps.io"
      hls_base_url    = "http://itg-feed-dev-app.internal.example.australiaeast.azurecontainerapps.io/hls"
    }
  }
}

run "service_boundaries" {
  command = plan

  assert {
    condition     = length(azurerm_postgresql_flexible_server_database.user) == 2
    error_message = "Keep accounts and matchapp as separate databases on the user server."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server_firewall_rule.azure_services.end_ip_address == "0.0.0.0"
    error_message = "The user database admits Azure services only, never the internet."
  }
  assert {
    condition     = !azurerm_container_app.backend[0].ingress[0].external_enabled && azurerm_container_app.frontend[0].ingress[0].external_enabled
    error_message = "Only the frontend is public; the backend is reached through it."
  }
  assert {
    condition     = toset([for s in azurerm_container_app.backend[0].secret : s.name]) == toset(concat(["acr-password"], keys(azurerm_key_vault_secret.backend)))
    error_message = "Backend secrets come from Key Vault through its managed identity."
  }
  assert {
    condition     = azurerm_container_app.frontend[0].template[0].min_replicas == 0
    error_message = "The frontend scales to zero."
  }
  assert {
    condition = alltrue([for e in azurerm_container_app.frontend[0].template[0].container[0].env :
    strcontains(e.value, ".internal.") if contains(["ETL_ADMIN_UPSTREAM", "ENGINE_ADMIN_UPSTREAM"], e.name)])
    error_message = "The dev consoles reach each owner's purge on its internal address."
  }
  assert {
    condition     = toset([for e in azurerm_container_app.frontend[0].template[0].container[0].env : e.secret_name if e.name == "ETL_ADMIN_TOKEN" || e.name == "ENGINE_ADMIN_TOKEN"]) == toset(["etl-admin-token", "engine-admin-token"])
    error_message = "Purge tokens reach nginx as Container Apps secrets."
  }
  assert {
    condition     = strcontains(azurerm_container_app.backend[0].template[0].container[0].env[index([for e in azurerm_container_app.backend[0].template[0].container[0].env : e.name], "NARRATIVE_GRAPHQL_URL")].value, ".internal.")
    error_message = "The backend reads the engine's GraphQL on its internal address."
  }
}

run "dev_consoles_off" {
  command = plan
  variables {
    dev_admin = false
  }
  assert {
    condition     = length(random_password.dev_admin) == 0 && length(azurerm_container_app.frontend[0].secret) == 1
    error_message = "With dev_admin off there is no console password."
  }
}
