terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.10" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Local state; `./dev azure` keeps it in .local/terraform/feed (-backend-config=path=...).
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
