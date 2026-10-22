data "azurerm_client_config" "current" {}

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
  name = "${var.name_prefix}-${random_string.suffix.result}"
  me   = data.azurerm_client_config.current.object_id
  tags = { project = "insidethegame", service = "narrative-engine", environment = "dev" }
}

resource "azurerm_resource_group" "narrative" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_consumption_budget_resource_group" "narrative" {
  name              = "budget-${var.name_prefix}"
  resource_group_id = azurerm_resource_group.narrative.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start
  }

  lifecycle {
    ignore_changes = [time_period] # azure.py passes the current month; an existing budget keeps its start.
  }

  dynamic "notification" {
    for_each = [25, 50, 90]
    content {
      operator       = "GreaterThanOrEqualTo"
      threshold      = notification.value
      threshold_type = "Actual"
      contact_emails = var.budget_emails
    }
  }
}
