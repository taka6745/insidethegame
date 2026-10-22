output "stream_start_action_group_id" {
  value       = azurerm_monitor_action_group.mode["stream-start"].id
  description = "etl/infra: Event Hubs traffic starts Stream Analytics."
}

output "stream_stop_action_group_id" {
  value       = azurerm_monitor_action_group.mode["stream-stop"].id
  description = "etl/infra: no Event Hubs traffic stops Stream Analytics."
}

output "stream_start_webhook_url" {
  value       = azurerm_automation_webhook.mode["stream-start"].uri
  sensitive   = true
  description = "Demo control: a demo Start asks for Stream Analytics at once instead of waiting for the traffic alert."
}
