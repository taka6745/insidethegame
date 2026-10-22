output "user_databases" { value = sort(keys(azurerm_postgresql_flexible_server_database.user)) }

output "resource_group" { value = azurerm_resource_group.app.name }

output "public_url" {
  description = "The viewer"
  value       = length(azurerm_container_app.frontend) > 0 ? "https://${azurerm_container_app.frontend[0].ingress[0].fqdn}" : null
}

output "backend_url" {
  description = "Internal; the engine's user_backend_url"
  value       = "http://${local.backend_host}"
}

output "key_vault_name" { value = azurerm_key_vault.app.name }

output "dev_admin_password" {
  description = "Basic auth for /dev/ (user `dev`)"
  value       = var.dev_admin ? random_password.dev_admin[0].result : null
  sensitive   = true
}
