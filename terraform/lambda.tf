resource "aws_cloudwatch_log_group" "scanner" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "scanner" {
  function_name = local.lambda_name
  description   = "Cloud Cost Guardian scheduled read-only scan"
  role          = aws_iam_role.scanner.arn
  handler       = "cloud_cost_guardian.lambda_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 300
  memory_size   = 256

  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = merge(
      {
        CCG_MODE                  = "aws"
        CCG_AWS_REGION            = local.region
        CCG_NOTIFICATION_PROVIDER = "sns"
        CCG_SNS_TOPIC_ARN         = aws_sns_topic.reports.arn
        CCG_LOG_FORMAT            = "json"
      },
      var.scanner_config,
    )
  }

  depends_on = [
    aws_iam_role_policy_attachment.scanner_readonly,
    aws_cloudwatch_log_group.scanner,
  ]
}
