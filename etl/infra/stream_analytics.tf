# Created stopped. Start/stop with `python -m devtools asa start|stop`; it bills only while running.
# Stop the job before `terraform apply` changes the query, inputs or outputs.
resource "azurerm_stream_analytics_job" "etl" {
  name                                     = "${local.name}-asa"
  location                                 = azurerm_resource_group.etl.location
  resource_group_name                      = azurerm_resource_group.etl.name
  sku_name                                 = "StandardV2"
  streaming_units                          = 3 # V2 scale: 3 = one third of a streaming unit, the minimum
  compatibility_level                      = "1.2"
  data_locale                              = "en-US"
  events_out_of_order_policy               = "Adjust"
  events_out_of_order_max_delay_in_seconds = 2
  events_late_arrival_max_delay_in_seconds = 5
  output_error_policy                      = "Drop" # one bad row must not stall every output; verify catches gaps
  transformation_query                     = templatefile("${path.module}/../stream-analytics/query.asaql", local.query_vars)
  tags                                     = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_stream_analytics_stream_input_eventhub_v2" "match_events" {
  name                         = "match-events"
  stream_analytics_job_id      = azurerm_stream_analytics_job.etl.id
  eventhub_name                = azurerm_eventhub.match_events.name
  servicebus_namespace         = azurerm_eventhub_namespace.etl.name
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumers["stream-analytics"].name
  partition_key                = "matchId"
  # LATER: switch to "Msi" (+ asa_eventhub_receiver role) once we can create role assignments.
  authentication_mode       = "ConnectionString"
  shared_access_policy_name = azurerm_eventhub_authorization_rule.asa_listen.name
  shared_access_policy_key  = azurerm_eventhub_authorization_rule.asa_listen.primary_key

  serialization {
    type     = "Json"
    encoding = "UTF8"
  }
}

# The same hub without TIMESTAMP BY: arrival (send) order, for the watermark marks (query.asaql step 9).
resource "azurerm_stream_analytics_stream_input_eventhub_v2" "match_progress" {
  name                         = "match-progress"
  stream_analytics_job_id      = azurerm_stream_analytics_job.etl.id
  eventhub_name                = azurerm_eventhub.match_events.name
  servicebus_namespace         = azurerm_eventhub_namespace.etl.name
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumers["stream-analytics-progress"].name
  partition_key                = "matchId"
  authentication_mode          = "ConnectionString"
  shared_access_policy_name    = azurerm_eventhub_authorization_rule.asa_listen.name
  shared_access_policy_key     = azurerm_eventhub_authorization_rule.asa_listen.primary_key

  serialization {
    type     = "Json"
    encoding = "UTF8"
  }
}

# Azure SQL's INSTEAD OF INSERT triggers (sql/azure/asa-progress.sql) gate these rows on tombstones and
# turn matchProgressMarks into matchProgress.
resource "azurerm_stream_analytics_output_mssql" "tables" {
  for_each                  = local.tables
  name                      = each.key
  stream_analytics_job_name = azurerm_stream_analytics_job.etl.name
  resource_group_name       = azurerm_resource_group.etl.name
  server                    = azurerm_mssql_server.etl.fully_qualified_domain_name
  database                  = azapi_resource.database.name
  table                     = each.key
  authentication_mode       = "Msi"
}

resource "azurerm_stream_analytics_output_servicebus_topic" "notifications" {
  name                      = "notifications"
  stream_analytics_job_name = azurerm_stream_analytics_job.etl.name
  resource_group_name       = azurerm_resource_group.etl.name
  topic_name                = azurerm_servicebus_topic.notifications.name
  servicebus_namespace      = azurerm_servicebus_namespace.etl.name
  # LATER: switch to "Msi" (+ asa_servicebus_sender role) once we can create role assignments.
  authentication_mode       = "ConnectionString"
  shared_access_policy_name = azurerm_servicebus_topic_authorization_rule.asa_send.name
  shared_access_policy_key  = azurerm_servicebus_topic_authorization_rule.asa_send.primary_key
  property_columns          = ["notificationType"]
  system_property_columns   = { MessageId = "sbMessageId" }

  serialization {
    type     = "Json"
    encoding = "UTF8"
    format   = "LineSeparated"
  }
}

locals {
  query_vars = { window_seconds = var.window_seconds, idle_seconds = var.watermark_idle_seconds }
  udfs = {
    hasQ           = { inputs = ["array", "bigint"], output = "bigint" }
    qValue         = { inputs = ["array", "bigint"], output = "nvarchar(max)" }
    toJson         = { inputs = ["any"], output = "nvarchar(max)" }
    matchInfo      = { inputs = ["any"], output = "record" }
    matchTeams     = { inputs = ["any"], output = "array" }
    matchPlayers   = { inputs = ["any"], output = "array" }
    canonicalEvent = { inputs = ["any"], output = "record" }
  }
}

resource "azurerm_stream_analytics_function_javascript_udf" "udfs" {
  for_each                  = local.udfs
  name                      = each.key
  stream_analytics_job_name = azurerm_stream_analytics_job.etl.name
  resource_group_name       = azurerm_resource_group.etl.name
  script                    = file("${path.module}/../stream-analytics/udfs/${each.key}.js")

  dynamic "input" {
    for_each = each.value.inputs
    content {
      type = input.value
    }
  }

  output {
    type = each.value.output
  }
}

# LATER: managed-identity roles, restored when the account can create role assignments (Contributor cannot).
# resource "azurerm_role_assignment" "asa_eventhub_receiver"  -> "Azure Event Hubs Data Receiver" on the hub
# resource "azurerm_role_assignment" "asa_servicebus_sender"  -> "Azure Service Bus Data Sender" on the topic
