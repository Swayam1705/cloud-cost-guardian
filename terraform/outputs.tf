output "lambda_function_name" {
  value       = aws_lambda_function.scanner.function_name
  description = "Name of the scheduled scanner Lambda"
}

output "scanner_role_arn" {
  value       = aws_iam_role.scanner.arn
  description = "Read-only role used by the scanner"
}

output "remediation_role_arn" {
  value       = var.enable_remediation_role ? aws_iam_role.remediation[0].arn : null
  description = "Separate remediation role (null unless enable_remediation_role = true)"
}

output "sns_topic_arn" {
  value       = aws_sns_topic.reports.arn
  description = "Topic that receives scan reports"
}

output "schedule" {
  value       = aws_cloudwatch_event_rule.schedule.schedule_expression
  description = "Scan schedule"
}
