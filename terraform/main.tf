# The user backend and frontend. Brokers, ETL GraphQL, the Container Apps environment and the
# registry come from etl/infra; Foundry and the narratives topic from narrative-engine/infra; the HLS
# origin from data-generation/infra (the simulated provider). All read from their local state.
data "terraform_remote_state" "etl" {
  backend = "local"
  config  = { path = var.etl_state_path }
}

data "terraform_remote_state" "narrative" {
  backend = "local"
  config  = { path = var.narrative_state_path }
}

data "terraform_remote_state" "feed" {
  backend = "local"
  config  = { path = var.feed_state_path }
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  etl       = data.terraform_remote_state.etl.outputs
  narrative = data.terraform_remote_state.narrative.outputs
  feed      = data.terraform_remote_state.feed.outputs
  name      = "${var.prefix}-${random_string.suffix.result}"
  domain    = local.etl.container_app_domain
  # Internal addresses (plain HTTP inside the environment), known before the apps exist.
  backend_host  = "${var.prefix}-backend.internal.${local.domain}"
  engine_host   = "${local.narrative.engine_app_name}.internal.${local.domain}"
  narrative_url = "https://${local.engine_host}/graphql"
}

resource "azurerm_resource_group" "app" {
  name     = "${var.prefix}-rg"
  location = var.location
  tags     = { project = "InsideTheGame", environment = "hackathon" }
}
