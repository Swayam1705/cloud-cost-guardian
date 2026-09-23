variable "aws_region" {
  description = "Region to deploy the optional scheduled scanner into (and to scan)."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile to use. Leave null to use the default credential chain / OIDC."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Prefix for all created resource names."
  type        = string
  default     = "cloud-cost-guardian"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,40}$", var.name_prefix))
    error_message = "name_prefix must be lowercase alphanumeric/hyphen, 3-41 chars."
  }
}

variable "schedule_expression" {
  description = "EventBridge schedule for the read-only scan. Weekly by default to keep invocations minimal."
  type        = string
  default     = "rate(7 days)"
}

variable "lambda_package_path" {
  description = "Path to the pre-built Lambda zip (see docs/deployment.md). Built outside Terraform so Terraform never installs pip packages."
  type        = string
  default     = "../lambda_package.zip"
}

variable "notification_email" {
  description = "Optional e-mail to subscribe to the SNS topic. Null = no subscription created."
  type        = string
  default     = null

  validation {
    condition     = var.notification_email == null || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be a valid e-mail address or null."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda log group."
  type        = number
  default     = 14
}

variable "enable_remediation_role" {
  description = "Create the SEPARATE remediation IAM role (never attached to the Lambda). Off by default."
  type        = bool
  default     = false
}

variable "scanner_config" {
  description = "Non-secret CCG_* environment overrides for the Lambda (thresholds, protected tags, ...)."
  type        = map(string)
  default     = {}
}
