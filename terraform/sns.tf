resource "aws_sns_topic" "reports" {
  name = "${var.name_prefix}-reports"
}

data "aws_iam_policy_document" "sns_topic" {
  statement {
    sid     = "AllowScannerPublish"
    actions = ["sns:Publish"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.scanner.arn]
    }
    resources = [aws_sns_topic.reports.arn]
  }
}

resource "aws_sns_topic_policy" "reports" {
  arn    = aws_sns_topic.reports.arn
  policy = data.aws_iam_policy_document.sns_topic.json
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email == null ? 0 : 1
  topic_arn = aws_sns_topic.reports.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
