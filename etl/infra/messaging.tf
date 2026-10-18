# Event Hubs: Standard tier, because Basic allows only one consumer group.
resource "azurerm_eventhub_namespace" "etl" {
  name                = "${local.name}-ehns"
  location            = azurerm_resource_group.etl.location
  resource_group_name = azurerm_resource_group.etl.name
  sku                 = "Standard"
  capacity            = 1
  tags                = local.tags
}

resource "azurerm_eventhub" "match_events" {
  name              = "match-events"
  namespace_id      = azurerm_eventhub_namespace.etl.id
  partition_count   = 2
  message_retention = 1
}

resource "azurerm_eventhub_consumer_group" "consumers" {
  for_each            = toset(["stream-analytics", "user-backend"])
  name                = each.key
  namespace_name      = azurerm_eventhub_namespace.etl.name
  eventhub_name       = azurerm_eventhub.match_events.name
  resource_group_name = azurerm_resource_group.etl.name
}

# Service Bus: Standard tier, because Basic has no topics.
resource "azurerm_servicebus_namespace" "etl" {
  name                = "${local.name}-sbns"
  location            = azurerm_resource_group.etl.location
  resource_group_name = azurerm_resource_group.etl.name
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_servicebus_topic" "notifications" {
  name                                    = "match-notifications"
  namespace_id                            = azurerm_servicebus_namespace.etl.id
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT10M"
  default_message_ttl                     = "P1D"
}

# One subscription per consumer; the narrative engine takes every message type.
resource "azurerm_servicebus_subscription" "narrative_engine" {
  name               = "narrative-engine"
  topic_id           = azurerm_servicebus_topic.notifications.id
  max_delivery_count = 10
}

# Shared access keys, scoped to one right each, because this account (Contributor) cannot create role
# assignments. LATER: replace with managed identity / Entra roles and remove these rules:
#   you  -> "Azure Event Hubs Data Sender" on the hub, "Azure Service Bus Data Receiver" on the topic.
resource "azurerm_eventhub_authorization_rule" "asa_listen" {
  name                = "stream-analytics-listen"
  namespace_name      = azurerm_eventhub_namespace.etl.name
  eventhub_name       = azurerm_eventhub.match_events.name
  resource_group_name = azurerm_resource_group.etl.name
  listen              = true
}

resource "azurerm_eventhub_authorization_rule" "seeder_send" {
  name                = "seeder-send"
  namespace_name      = azurerm_eventhub_namespace.etl.name
  eventhub_name       = azurerm_eventhub.match_events.name
  resource_group_name = azurerm_resource_group.etl.name
  send                = true
}

resource "azurerm_servicebus_topic_authorization_rule" "asa_send" {
  name     = "stream-analytics-send"
  topic_id = azurerm_servicebus_topic.notifications.id
  send     = true
}

# For consumers (narrative engine, verification scripts) to read their subscription.
resource "azurerm_servicebus_topic_authorization_rule" "consumers_listen" {
  name     = "consumers-listen"
  topic_id = azurerm_servicebus_topic.notifications.id
  listen   = true
}
