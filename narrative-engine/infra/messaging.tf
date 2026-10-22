# Topics live in the ETL's Standard Service Bus namespace (no second namespace to pay for).
# The engine reads match-notifications through the ETL's `narrative-engine` subscription.
# Live narratives for the user backend: one message per bucket narrative, MessageId = narrative id.
resource "azurerm_servicebus_topic" "narratives" {
  name                                    = "narratives"
  namespace_id                            = data.terraform_remote_state.etl.outputs.servicebus_namespace_id
  requires_duplicate_detection            = true
  duplicate_detection_history_time_window = "PT10M"
  default_message_ttl                     = "P1D"
}

# narrative-check: our own end-to-end checks; short TTL so unread test messages expire.
resource "azurerm_servicebus_subscription" "narratives" {
  for_each            = { "user-backend" = "P1D", "narrative-check" = "PT1H" }
  name                = each.key
  topic_id            = azurerm_servicebus_topic.narratives.id
  max_delivery_count  = 10
  default_message_ttl = each.value
}

# Shared access keys, one right each, because this account (Contributor) cannot create role
# assignments. LATER: replace with managed identity / Entra roles, as in etl/infra.
resource "azurerm_servicebus_topic_authorization_rule" "narratives_send" {
  name     = "narrative-engine-send"
  topic_id = azurerm_servicebus_topic.narratives.id
  send     = true
}

resource "azurerm_servicebus_topic_authorization_rule" "narratives_listen" {
  name     = "consumers-listen"
  topic_id = azurerm_servicebus_topic.narratives.id
  listen   = true
}
