# Application Insights for Agent Framework's traces (agent runs, model calls, latency, tokens) and the
# engine's logs. Its own small workspace, so engine telemetry cannot use up the ETL workspace's cap.
resource "azurerm_log_analytics_workspace" "engine" {
  name                = "${local.name}-logs"
  location            = azurerm_resource_group.narrative.location
  resource_group_name = azurerm_resource_group.narrative.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.2
  tags                = local.tags
}

resource "azurerm_application_insights" "engine" {
  name                = "${local.name}-appi"
  location            = azurerm_resource_group.narrative.location
  resource_group_name = azurerm_resource_group.narrative.name
  workspace_id        = azurerm_log_analytics_workspace.engine.id
  application_type    = "other"
  tags                = local.tags
}

# A ready-made workbook (Application Insights -> Workbooks -> "Narrative engine"): agent runs,
# latency, tokens, failures and warnings. Counts use itemCount because traces are sampled.
resource "random_uuid" "workbook" {}

locals {
  workbook_time = { timeContext = { durationMs = 0 }, timeContextFromParameter = "TimeRange" }
  workbook_queries = [
    { title = "Agent runs", visualization = "table", query = <<-KQL
        dependencies
        | where name startswith "invoke_agent"
        | extend tokens = toint(customDimensions["gen_ai.usage.input_tokens"]) + toint(customDimensions["gen_ai.usage.output_tokens"])
        | summarize runs = sum(itemCount), avg_ms = round(avg(duration)), p95_ms = round(percentile(duration, 95)),
            avg_tokens = round(avg(tokens)), failed = sumif(itemCount, success == false) by agent = substring(name, 13)
        KQL
    },
    { title = "Agent latency (avg ms)", visualization = "timechart", query = <<-KQL
        dependencies
        | where name startswith "invoke_agent"
        | summarize avg(duration) by agent = substring(name, 13), bin(timestamp, 1m)
        KQL
    },
    { title = "Tokens per minute", visualization = "timechart", query = <<-KQL
        dependencies
        | where name startswith "invoke_agent"
        | extend tokens = toint(customDimensions["gen_ai.usage.input_tokens"]) + toint(customDimensions["gen_ai.usage.output_tokens"])
        | summarize sum(tokens * itemCount) by agent = substring(name, 13), bin(timestamp, 1m)
        KQL
    },
    { title = "Narratives published per minute", visualization = "barchart", query = <<-KQL
        dependencies
        | where name == "ServiceBus.send"
        | summarize narratives = sum(itemCount) by bin(timestamp, 1m)
        KQL
    },
    { title = "Failed calls", visualization = "table", query = <<-KQL
        dependencies
        | where success == false
        | summarize failures = sum(itemCount), last = max(timestamp) by name, resultCode
        | order by failures desc
        KQL
    },
    { title = "Engine warnings and errors", visualization = "table", query = <<-KQL
        union traces, exceptions
        | where severityLevel >= 2 or itemType == "exception"
        | project timestamp, severityLevel, message = coalesce(message, outerMessage)
        | order by timestamp desc
        | take 100
        KQL
    },
  ]
}

resource "azurerm_application_insights_workbook" "engine" {
  name                = random_uuid.workbook.result
  location            = azurerm_resource_group.narrative.location
  resource_group_name = azurerm_resource_group.narrative.name
  display_name        = "Narrative engine"
  source_id           = lower(azurerm_application_insights.engine.id)
  tags                = local.tags
  data_json = jsonencode({
    version = "Notebook/1.0"
    items = concat([
      { type = 1, name = "intro", content = { json = "## Narrative engine\nAgent Framework traces from the deployed engine. Data arrives 2-5 minutes after it happens; traces are sampled, so counts use `itemCount`." } },
      { type = 9, name = "parameters", content = {
        version = "KqlParameterItem/1.0"
        parameters = [{
          id           = "8f4b6a52-6b8c-4c39-9a57-3a1f0c2d7e10", version = "KqlParameterItem/1.0", name = "TimeRange", type = 4,
          value        = { durationMs = 14400000 }
          typeSettings = { selectableValues = [for ms in [3600000, 14400000, 86400000, 604800000] : { durationMs = ms }] }
        }]
      } },
      ], [for i, q in local.workbook_queries : {
        type = 3, name = "query-${i}", content = merge(local.workbook_time, {
          version      = "KqlItem/1.0", title = q.title, query = trimspace(q.query), size = 0, queryType = 0,
          resourceType = "microsoft.insights/components", visualization = q.visualization
        })
    }])
    fallbackResourceIds = [lower(azurerm_application_insights.engine.id)]
  })
}
