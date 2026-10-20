data "azurerm_client_config" "current" {}

# Your public IP, so sqlcmd from this machine can reach Azure SQL.
data "http" "my_ip" {
  url = "https://api.ipify.org"
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name   = "${var.name_prefix}-${random_string.suffix.result}"
  me     = data.azurerm_client_config.current.object_id
  my_ip  = chomp(data.http.my_ip.response_body)
  tables = toset(["matches", "rawEvents", "keyEvents", "minuteStats"])
  tags   = { project = "insidethegame", service = "etl", environment = "dev" }
}

resource "azurerm_resource_group" "etl" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_consumption_budget_resource_group" "etl" {
  name              = "budget-${var.name_prefix}"
  resource_group_id = azurerm_resource_group.etl.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start
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
