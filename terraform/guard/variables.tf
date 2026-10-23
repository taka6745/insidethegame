variable "subscription_id" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Budget alerts go here; ./dev azure passes the signed-in account (never committed)."
}

variable "daily_cap" {
  type        = number
  default     = 15
  description = "Spend per day, in the billing currency (AUD here), that warrants an email; the budget is 30x this a month."
}

variable "daily_actual_percent" {
  type    = list(number)
  default = [50, 80, 100]
}

variable "credit_amount" {
  type        = number
  default     = 285
  description = "Spend from credit_start that uses up the trial credit."
}

variable "credit_start" {
  type    = string
  default = "2026-10-01T00:00:00Z"
}

variable "credit_end" {
  type        = string
  default     = "2026-12-31T00:00:00Z"
  description = "The budget runs to the quarter's end, past the credit's expiry."
}

variable "credit_actual_percent" {
  type    = list(number)
  default = [50, 75]
}

variable "last_resort_percent" {
  type        = number
  default     = 90
  description = "Actual share of the credit at which the non-serving parts stop (about A$28, several idle days, left)."
}

variable "last_resort_apps" {
  type        = list(string)
  default     = ["-feed", "-spadl"]
  description = "Container app name suffixes the last resort stops; the viewer's apps (frontend, backend, DAB, engine) keep running."
}

variable "last_resort_server_group" {
  type        = string
  default     = "rg-itg-feed-dev"
  description = "PostgreSQL servers in this group (the feed's) stop in the last resort."
}

variable "guarded_groups" {
  type    = list(string)
  default = ["rg-itg-etl-dev", "rg-itg-narrative-dev", "rg-itg-feed-dev", "itgdemo-rg"]
}

variable "etl_group" {
  type    = string
  default = "rg-itg-etl-dev"
}

variable "resource_group" {
  type    = string
  default = "rg-itg-guard"
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "automation_location" {
  type        = string
  default     = "eastus"
  description = "Free Trial subscriptions may create Automation accounts only in a few regions (not Australia East)."
}

variable "budget_start" {
  type        = string
  description = "First day of the current month (UTC), RFC 3339; ./dev azure passes it."
  default     = "2026-10-01T00:00:00Z"
}

variable "webhook_expiry" {
  type    = string
  default = "2027-10-01T00:00:00Z"
}
