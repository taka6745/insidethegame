# Spend guard and idle saver, applied first by `./dev azure up` and kept after `down` (budgets, action groups,
# an Automation account and its alerts cost nothing idle).
# - Budgets email only: the live demo must never be interrupted by a daily cap.
# - One last resort: when actual spend nears the remaining credit, stop what doesn't serve the viewer
#   (Stream Analytics, the feed, the SPADL post-processor, the feed's database). Viewer and replays keep working.
# - Stream Analytics runs only while matches play: the ETL's Event Hubs alerts call the runbook to start and
#   stop it (etl/infra stream_schedule.tf).
# The runbook stops and starts; it never deletes.

terraform {
  required_version = "~> 1.13.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.10" }
  }
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}

locals {
  subscription = "/subscriptions/${var.subscription_id}"
  monthly      = var.daily_cap * 30                  # Azure budgets have no daily grain
  tags         = { project = "insidethegame-guard" } # not the app's tag: `down` leaves the guard alone
  modes        = toset(["last-resort", "stream-start", "stream-stop"])
}

resource "azurerm_resource_group" "guard" {
  name     = var.resource_group
  location = var.location
  tags     = local.tags
}

resource "azurerm_automation_account" "guard" {
  name                = "itg-spend-guard"
  location            = var.automation_location
  resource_group_name = azurerm_resource_group.guard.name
  sku_name            = "Basic"
  tags                = local.tags
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_automation_runbook" "guard" {
  name                    = "insidethegame-guard"
  location                = azurerm_automation_account.guard.location
  resource_group_name     = azurerm_resource_group.guard.name
  automation_account_name = azurerm_automation_account.guard.name
  runbook_type            = "PowerShell72"
  log_progress            = false
  log_verbose             = false
  description             = "Starts/stops Stream Analytics with play; last resort stops the non-serving parts."
  content = templatefile("${path.module}/guard.ps1", {
    groups    = join(",", [for g in var.guarded_groups : "'${g}'"])
    etl_group = var.etl_group
    apps      = join(",", [for a in var.last_resort_apps : "'${a}'"])
    servers   = var.last_resort_server_group
  })
  tags = local.tags
}

# One webhook per mode; the URI is shown only at creation.
resource "azurerm_automation_webhook" "mode" {
  for_each                = local.modes
  name                    = each.key
  resource_group_name     = azurerm_resource_group.guard.name
  automation_account_name = azurerm_automation_account.guard.name
  runbook_name            = azurerm_automation_runbook.guard.name
  expiry_time             = var.webhook_expiry
  parameters              = { mode = each.key }
  lifecycle {
    ignore_changes = [expiry_time]
  }
}

# Least privilege: read, start and stop; never write or delete. The runbook limits itself to our groups.
resource "azurerm_role_definition" "guard" {
  name  = "InsideTheGame spend guard"
  scope = local.subscription
  permissions {
    actions = [
      "Microsoft.Resources/subscriptions/resourceGroups/read",
      "Microsoft.Resources/subscriptions/resourceGroups/resources/read",
      "Microsoft.StreamAnalytics/streamingjobs/read",
      "Microsoft.StreamAnalytics/streamingjobs/start/action",
      "Microsoft.StreamAnalytics/streamingjobs/stop/action",
      "Microsoft.App/containerApps/read",
      "Microsoft.App/containerApps/stop/action",
      "Microsoft.DBforPostgreSQL/flexibleServers/read",
      "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
    ]
  }
  assignable_scopes = [local.subscription]
}

resource "azurerm_role_assignment" "guard" {
  scope              = local.subscription
  role_definition_id = azurerm_role_definition.guard.role_definition_resource_id
  principal_id       = azurerm_automation_account.guard.identity[0].principal_id
}

resource "azurerm_monitor_action_group" "email" {
  name                = "itg-spend-email"
  resource_group_name = azurerm_resource_group.guard.name
  short_name          = "itgspend"
  tags                = local.tags
  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_action_group" "mode" {
  for_each            = local.modes
  name                = "itg-${each.key}"
  resource_group_name = azurerm_resource_group.guard.name
  short_name          = substr(replace("itg${each.key}", "-", ""), 0, 12)
  tags                = local.tags
  dynamic "email_receiver" {
    for_each = each.key == "last-resort" ? [1] : []
    content {
      name                    = "owner"
      email_address           = var.alert_email
      use_common_alert_schema = true
    }
  }
  automation_runbook_receiver {
    name                    = each.key
    automation_account_id   = azurerm_automation_account.guard.id
    runbook_name            = azurerm_automation_runbook.guard.name
    webhook_resource_id     = azurerm_automation_webhook.mode[each.key].id
    is_global_runbook       = false
    service_uri             = azurerm_automation_webhook.mode[each.key].uri
    use_common_alert_schema = true
  }
}

# The daily cap: email only.
resource "azurerm_consumption_budget_subscription" "daily" {
  name            = "budget-insidethegame"
  subscription_id = local.subscription
  amount          = local.monthly
  time_grain      = "Monthly"
  time_period {
    start_date = var.budget_start
  }
  lifecycle {
    ignore_changes = [time_period] # azure.py passes the current month; an existing budget keeps its start
  }
  dynamic "notification" {
    for_each = var.daily_actual_percent
    content {
      threshold      = notification.value
      threshold_type = "Actual"
      operator       = "GreaterThanOrEqualTo"
      contact_groups = [azurerm_monitor_action_group.email.id]
    }
  }
  notification {
    threshold      = 100
    threshold_type = "Forecasted"
    operator       = "GreaterThanOrEqualTo"
    contact_groups = [azurerm_monitor_action_group.email.id]
  }
}

# The credit: spend from the period start that would use it up. Emails early; the last resort fires on actual
# spend only, because a forecast runs to the period end and would stop the demo too soon.
resource "azurerm_consumption_budget_subscription" "credit" {
  name            = "budget-insidethegame-credit"
  subscription_id = local.subscription
  amount          = var.credit_amount
  time_grain      = "Quarterly"
  time_period {
    start_date = var.credit_start
    end_date   = var.credit_end
  }
  dynamic "notification" {
    for_each = var.credit_actual_percent
    content {
      threshold      = notification.value
      threshold_type = "Actual"
      operator       = "GreaterThanOrEqualTo"
      contact_groups = [azurerm_monitor_action_group.email.id]
    }
  }
  notification {
    threshold      = 100
    threshold_type = "Forecasted"
    operator       = "GreaterThanOrEqualTo"
    contact_groups = [azurerm_monitor_action_group.email.id]
  }
  notification {
    threshold      = var.last_resort_percent
    threshold_type = "Actual"
    operator       = "GreaterThanOrEqualTo"
    contact_groups = [azurerm_monitor_action_group.mode["last-resort"].id]
  }
}

moved {
  from = azurerm_role_definition.stop
  to   = azurerm_role_definition.guard
}

moved {
  from = azurerm_role_assignment.stop
  to   = azurerm_role_assignment.guard
}

moved {
  from = azurerm_consumption_budget_subscription.cap
  to   = azurerm_consumption_budget_subscription.daily
}
