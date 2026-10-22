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

variable "watermark_idle_seconds" {
  type        = number
  default     = 3
  description = "Quiet spell after which a match's latest event counts as complete (local ETL_WATERMARK_IDLE_SECONDS)."
}

variable "admin_image_tag" {
  type        = string
  default     = null
  description = "etl-stream image tag in the ETL registry; set after `az acr build` to run the purge API (admin.tf)."
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

variable "stream_start_action_group_id" {
  type        = string
  default     = null
  description = "terraform/guard output: called when match events arrive, to start Stream Analytics. Null: no schedule."
}

variable "stream_stop_action_group_id" {
  type        = string
  default     = null
  description = "terraform/guard output: called after stream_idle_window without match events, to stop Stream Analytics."
}

variable "stream_idle_window" {
  type        = string
  default     = "PT30M"
  description = "No match events for this long stops Stream Analytics (longer than half time; an ISO 8601 metric alert window)."
}

variable "demo_seeds" {
  type        = bool
  default     = false
  description = "Demo seed export/restore routes (DEMO_SEEDS=1; PLAN.md §10.6). On for the judge build (`./dev azure up`), off for a production release."
}

variable "sql_after_free_limit" {
  type        = string
  default     = "BillOverUsage"
  description = "When the monthly free vCore-seconds run out: BillOverUsage (keeps serving) or AutoPause (free, but pauses until the next month)."
  validation {
    condition     = contains(["BillOverUsage", "AutoPause"], var.sql_after_free_limit)
    error_message = "BillOverUsage or AutoPause."
  }
}
