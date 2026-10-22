# Recordings, packaged media and played HLS (feed/adapters/blob.py). All private: the feed copies a
# segment into `live` only once it has played, and its /hls route streams from there.
resource "azurerm_storage_account" "feed" {
  name                            = replace("${local.name}st", "-", "")
  location                        = azurerm_resource_group.feed.location
  resource_group_name             = azurerm_resource_group.feed.name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_storage_container" "feed" {
  for_each              = toset(["recordings", "media", "live"])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.feed.id
  container_access_type = "private"
}
