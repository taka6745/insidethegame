terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 5.10" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Local state for now (personal dev environment), like etl/infra.
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
