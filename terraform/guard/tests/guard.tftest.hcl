# Mock provider: checks the guard's shape without Azure calls.
mock_provider "azurerm" {
  mock_resource "azurerm_automation_account" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-itg-guard/providers/Microsoft.Automation/automationAccounts/itg-spend-guard", identity = { type = "SystemAssigned", principal_id = "00000000-0000-0000-0000-000000000003", tenant_id = "00000000-0000-0000-0000-000000000001" } }
  }
  mock_resource "azurerm_role_definition" {
    defaults = { role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-000000000004" }
  }
  mock_resource "azurerm_automation_webhook" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-itg-guard/providers/Microsoft.Automation/automationAccounts/itg-spend-guard/webhooks/w", uri = "https://example.invalid/webhooks?token=mock" }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-itg-guard/providers/Microsoft.Insights/actionGroups/ag" }
  }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  alert_email     = "owner@example.com"
}

run "judging_is_never_stopped_by_the_daily_cap" {
  command = apply
  assert {
    condition     = azurerm_consumption_budget_subscription.daily.amount == 450
    error_message = "A$15/day is a 450 monthly budget."
  }
  assert {
    condition     = alltrue([for n in azurerm_consumption_budget_subscription.daily.notification : tolist(n.contact_groups) == tolist([azurerm_monitor_action_group.email.id])])
    error_message = "Every daily-cap notification goes to the email group only."
  }
  assert {
    condition     = length([for n in azurerm_consumption_budget_subscription.credit.notification : n if n.threshold_type == "Forecasted" && n.threshold >= 100]) == 1
    error_message = "The credit forecast only emails."
  }
}

run "the_guard_only_reads_starts_and_stops" {
  command = apply
  assert {
    condition     = length([for a in azurerm_role_definition.guard.permissions[0].actions : a if strcontains(a, "delete") || strcontains(a, "write")]) == 0
    error_message = "The guard may only read, start and stop."
  }
  assert {
    condition     = !contains(var.last_resort_apps, "-backend") && !contains(var.last_resort_apps, "-frontend")
    error_message = "The last resort keeps the viewer serving."
  }
  assert {
    condition     = length([for n in azurerm_consumption_budget_subscription.credit.notification : n if n.threshold_type == "Actual" && n.threshold == 100 && tolist(n.contact_groups) == tolist([azurerm_monitor_action_group.mode["hard-stop"].id])]) == 1
    error_message = "The whole credit, actually spent, runs the hard stop."
  }
  assert {
    condition     = var.hard_stop_percent > var.last_resort_percent
    error_message = "The last resort comes before the hard stop."
  }
  assert {
    condition     = azurerm_resource_group.guard.tags.project != "insidethegame"
    error_message = "The guard must not carry the app's tag, or `down` would delete it."
  }
}
