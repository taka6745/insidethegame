output "resource_group" {
  value = azurerm_resource_group.feed.name
}

output "storage_account" {
  description = "Upload recordings/*.json to `recordings` and {fixture}/hls/ to `media` (./dev azure up does)"
  value       = azurerm_storage_account.feed.name
}

output "app_name" {
  value = "${var.name_prefix}-app"
}

# Predictable before the app exists: <app>.internal.<environment domain>.
output "hls_origin_host" {
  description = "Internal HLS origin host for nginx (MEDIA_ORIGIN)"
  value       = "${var.name_prefix}-app.internal.${local.etl.container_app_domain}"
}

output "hls_base_url" {
  description = "FEED_HLS_BASE for the user backend"
  value       = "http://${var.name_prefix}-app.internal.${local.etl.container_app_domain}/hls"
}
