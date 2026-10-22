# The simulated external provider (data-generation/feed), isolated like a third party: its own
# resource group, database server and storage. It shares only the ETL's Container Apps environment
# (trial: one per region) and registry, and holds a send-only key for `match-events`.
data "terraform_remote_state" "etl" {
  backend = "local"
  config  = { path = var.etl_state_path }
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  etl  = data.terraform_remote_state.etl.outputs
  name = "${var.name_prefix}-${random_string.suffix.result}"
  tags = { project = "insidethegame", service = "feed", environment = "dev" }
}

resource "azurerm_resource_group" "feed" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = local.tags
}
