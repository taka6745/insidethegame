terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.10" }
    azapi   = { source = "Azure/azapi", version = "~> 2.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
    http    = { source = "hashicorp/http", version = "~> 3.4" }
  }
  # Local state; `./dev azure` keeps it in .local/terraform/<stack> (-backend-config=path=...).
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "azapi" {
  subscription_id = var.subscription_id
}
