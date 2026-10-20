variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "name_prefix" {
  type    = string
  default = "itg-narrative-dev"
}

variable "etl_state_path" {
  type        = string
  default     = "../../etl/infra/terraform.tfstate"
  description = "The ETL's local state, read (only) for its Service Bus namespace."
}

variable "budget_amount" {
  type        = number
  default     = 20
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

variable "models" {
  type = map(object({
    version  = string
    capacity = number # thousands of tokens per minute
    format   = optional(string, "OpenAI")
    sku      = optional(string, "GlobalStandard")
  }))
  default = {
    "gpt-5-mini" = { version = "2025-08-07", capacity = 100 } # GlobalStandard quota in Australia East: 500
  }
  description = "Foundry deployments, by model name."
}

variable "agents" {
  type = map(object({
    model  = string
    effort = optional(string) # reasoning_effort; omit for models without reasoning
  }))
  default = {
    summary     = { model = "gpt-5-mini", effort = "minimal" }
    compression = { model = "gpt-5-mini", effort = "minimal" }
    author      = { model = "gpt-5-mini", effort = "low" }
  }
  description = "Model (a key of var.models) and reasoning effort for each agent."

  validation {
    condition     = toset(keys(var.agents)) == toset(["summary", "compression", "author"])
    error_message = "Set exactly the agents summary, compression and author."
  }
}

variable "engine_image_tag" {
  type        = string
  default     = null
  description = "Image tag in the registry; the Container App is created once this is set."
}

variable "match_ids" {
  type        = string
  default     = ""
  description = "Optional comma-separated matchIds the deployed engine handles (empty = all)."
}
