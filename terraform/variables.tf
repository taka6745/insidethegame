variable "subscription_id" {
  description = "Real Azure subscription for a separately authorised cloud deployment. Mock tests supply a dummy ID."
  type        = string
}

variable "prefix" {
  description = "Globally unique lowercase prefix, 3-16 letters/digits, starting with a letter."
  type        = string
  default     = "itgdemo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.prefix))
    error_message = "Use 3-16 lowercase letters/digits, starting with a letter."
  }
}

variable "location" {
  type        = string
  default     = "australiaeast"
  description = "Check regional SKU availability before a cloud deployment."
}

variable "database_admin_password" {
  type        = string
  sensitive   = true
  description = "Cloud-only database admin password; supply outside Git. Local Docker uses public dummy credentials."
  validation {
    condition     = length(var.database_admin_password) >= 16
    error_message = "Use at least 16 characters and satisfy Azure SQL/PostgreSQL complexity requirements."
  }
}
