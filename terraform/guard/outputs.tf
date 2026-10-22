output "stream_start_action_group_id" {
  value       = azurerm_monitor_action_group.mode["stream-start"].id
  description = "etl/infra: Event Hubs traffic starts Stream Analytics."
}

output "stream_stop_action_group_id" {
  value       = azurerm_monitor_action_group.mode["stream-stop"].id
  description = "etl/infra: no Event Hubs traffic stops Stream Analytics."
}
