# Mock provider: checks the intended resource graph WITHOUT credentials or Azure calls.
mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  image_tag       = "test"
}

override_data {
  target = data.terraform_remote_state.etl
  values = {
    outputs = {
      container_app_environment_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/cae"
      container_app_domain            = "example.australiaeast.azurecontainerapps.io"
      registry_login_server           = "registry.azurecr.io"
      registry_username               = "registry"
      registry_password               = "mock"
      eventhub_send_connection_string = "Endpoint=sb://mock/;SharedAccessKeyName=seeder-send;SharedAccessKey=mock;EntityPath=match-events"
    }
  }
}

run "provider_isolation" {
  command = plan

  assert {
    condition     = azurerm_resource_group.feed.name == "rg-itg-feed-dev"
    error_message = "The feed is a third party: its own resource group."
  }
  assert {
    condition     = alltrue([for c in azurerm_storage_container.feed : c.container_access_type == "private"]) && !azurerm_storage_account.feed.allow_nested_items_to_be_public
    error_message = "Media stays private; HLS is served only through the feed's play-gated route."
  }
  assert {
    condition     = !azurerm_container_app.feed[0].ingress[0].external_enabled
    error_message = "The feed's admin API must not be on the internet."
  }
  assert {
    condition     = azurerm_container_app.feed[0].template[0].max_replicas == 1
    error_message = "Runs live in one process."
  }
  assert {
    condition     = output.hls_base_url == "http://itg-feed-dev-app.internal.example.australiaeast.azurecontainerapps.io/hls"
    error_message = "FEED_HLS_BASE is the internal origin."
  }
}

run "no_app_without_image" {
  command = plan
  variables {
    image_tag = null
  }
  assert {
    condition     = length(azurerm_container_app.feed) == 0
    error_message = "No placeholder app before an image exists."
  }
}
