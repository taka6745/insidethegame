variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "name_prefix" {
  type    = string
  default = "itg-etl-dev"
}

variable "window_seconds" {
  type        = number
  default     = 6
  description = "Stream Analytics tumbling window = one match minute = 60 / replay speed. Stop the job before changing."
}

variable "budget_amount" {
  type        = number
  default     = 50
  description = "Monthly budget for the resource group, in the subscription's billing currency."
}

variable "budget_emails" {
  type        = list(string)
  description = "Who gets budget alerts. Set in local.auto.tfvars (git-ignored)."
}

variable "budget_start" {
  type        = string
  default     = "2026-10-01T00:00:00Z"
  description = "First day of a month; budgets cannot start in the past when created."
}

variable "dab_image" {
  type    = string
  default = "mcr.microsoft.com/azure-databases/data-api-builder:2.1.5"
}
