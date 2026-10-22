# Stream Analytics runs only while matches play: Event Hubs traffic starts it, a quiet window stops it
# (terraform/guard's runbook). A start resumes after the last output, so events buffered in Event Hubs
# while the job was starting are processed, a minute or two late at kick-off. The alert itself takes 1-3 min
# (metric ingestion), so a demo Start also calls the guard's stream-start webhook at once (demo control,
# DEMO_STREAM_START_URL); the job's own start (~75-90 s) remains.
resource "azurerm_monitor_metric_alert" "stream_start" {
  count               = var.stream_start_action_group_id == null ? 0 : 1
  name                = "${local.name}-stream-start"
  resource_group_name = azurerm_resource_group.etl.name
  scopes              = [azurerm_eventhub_namespace.etl.id]
  description         = "Match events are arriving: start Stream Analytics."
  severity            = 4
  frequency           = "PT1M"
  window_size         = "PT1M"
  auto_mitigate       = true
  tags                = local.tags
  criteria {
    metric_namespace = "Microsoft.EventHub/namespaces"
    metric_name      = "IncomingMessages"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 0
    dimension {
      name     = "EntityName"
      operator = "Include"
      values   = [azurerm_eventhub.match_events.name]
    }
  }
  action {
    action_group_id = var.stream_start_action_group_id
  }
}

resource "azurerm_monitor_metric_alert" "stream_stop" {
  count               = var.stream_stop_action_group_id == null ? 0 : 1
  name                = "${local.name}-stream-stop"
  resource_group_name = azurerm_resource_group.etl.name
  scopes              = [azurerm_eventhub_namespace.etl.id]
  description         = "No match events for a while: stop Stream Analytics (it bills while running)."
  severity            = 4
  frequency           = "PT5M"
  window_size         = var.stream_idle_window
  auto_mitigate       = true
  tags                = local.tags
  criteria {
    metric_namespace = "Microsoft.EventHub/namespaces"
    metric_name      = "IncomingMessages"
    aggregation      = "Total"
    operator         = "LessThanOrEqual"
    threshold        = 0
    dimension {
      name     = "EntityName"
      operator = "Include"
      values   = [azurerm_eventhub.match_events.name]
    }
  }
  action {
    action_group_id = var.stream_stop_action_group_id
  }
}
