resource "azurerm_eventhub_namespace" "match" {
  name                = "${var.prefix}-events"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "Standard"
  capacity            = 1
}

resource "azurerm_eventhub" "match" {
  name              = "match-events"
  namespace_id      = azurerm_eventhub_namespace.match.id
  partition_count   = 2
  message_retention = 1
}

resource "azurerm_eventhub_consumer_group" "consumers" {
  for_each            = toset(["etl", "user-backend"])
  name                = each.value
  eventhub_name       = azurerm_eventhub.match.name
  namespace_name      = azurerm_eventhub_namespace.match.name
  resource_group_name = azurerm_resource_group.app.name
}

resource "azurerm_servicebus_namespace" "app" {
  name                = "${var.prefix}-messages"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "Standard"
}

resource "azurerm_servicebus_topic" "topics" {
  for_each     = toset(["match-notifications", "narratives"])
  name         = each.value
  namespace_id = azurerm_servicebus_namespace.app.id
}

resource "azurerm_servicebus_subscription" "consumers" {
  for_each = {
    narrative-engine = "match-notifications"
    user-backend     = "narratives"
  }
  name               = each.key
  topic_id           = azurerm_servicebus_topic.topics[each.value].id
  max_delivery_count = 5
}
