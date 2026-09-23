# ---------------------------------------------------------------------------
# Least-privilege IAM. Two deliberately separate policies:
#   1. scan (read-only)  -> attached to the Lambda
#   2. remediation       -> a separate role, never attached to the Lambda,
#                           only created when enable_remediation_role = true
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scanner" {
  name               = "${var.name_prefix}-scanner-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# --- Read/Scan permissions ---------------------------------------------------
data "aws_iam_policy_document" "scan_readonly" {
  # EC2 Describe* calls do not support resource-level permissions, hence "*".
  statement {
    sid = "DescribeEC2Resources"
    actions = [
      "ec2:DescribeVolumes",   # EBS detector
      "ec2:DescribeInstances", # EC2 detector
      "ec2:DescribeAddresses", # EIP detector
      "ec2:DescribeSnapshots", # snapshot detector
    ]
    resources = ["*"]
  }

  # RDS Describe supports resource-level ARNs; scope to DB instances in this account/region.
  statement {
    sid       = "DescribeRDSInstances"
    actions   = ["rds:DescribeDBInstances"] # RDS detector (TagList included in the response)
    resources = ["arn:${local.partition}:rds:${local.region}:${local.account_id}:db:*"]
  }

  statement {
    sid       = "ReadUtilizationMetrics"
    actions   = ["cloudwatch:GetMetricStatistics"] # EC2 / RDS CPU evidence
    resources = ["*"]
  }

  statement {
    sid       = "PublishReport"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.reports.arn]
  }

  statement {
    sid = "WriteOwnLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.scanner.arn}:*"]
  }
}

resource "aws_iam_policy" "scan_readonly" {
  name        = "${var.name_prefix}-scan-readonly"
  description = "Read-only permissions for Cloud Cost Guardian scans"
  policy      = data.aws_iam_policy_document.scan_readonly.json
}

resource "aws_iam_role_policy_attachment" "scanner_readonly" {
  role       = aws_iam_role.scanner.name
  policy_arn = aws_iam_policy.scan_readonly.arn
}

# --- Remediation permissions (separate, optional, human-assumed) -------------
data "aws_iam_policy_document" "remediation_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
    # Require MFA for anyone assuming the destructive role.
    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["true"]
    }
  }
}

data "aws_iam_policy_document" "remediation" {
  statement {
    sid = "DeleteUnattachedVolumes"
    actions = [
      "ec2:DeleteVolume",
    ]
    resources = ["arn:${local.partition}:ec2:${local.region}:${local.account_id}:volume/*"]
    # Never delete a protected volume even if the tool were misused.
    condition {
      test     = "StringNotEqualsIgnoreCase"
      variable = "aws:ResourceTag/cost-guardian-protected"
      values   = ["true"]
    }
  }

  statement {
    sid       = "ReleaseElasticIPs"
    actions   = ["ec2:ReleaseAddress"]
    resources = ["arn:${local.partition}:ec2:${local.region}:${local.account_id}:elastic-ip/*"]
    condition {
      test     = "StringNotEqualsIgnoreCase"
      variable = "aws:ResourceTag/cost-guardian-protected"
      values   = ["true"]
    }
  }

  statement {
    sid       = "DeleteOldSnapshots"
    actions   = ["ec2:DeleteSnapshot"]
    resources = ["arn:${local.partition}:ec2:${local.region}::snapshot/*"]
    condition {
      test     = "StringNotEqualsIgnoreCase"
      variable = "aws:ResourceTag/cost-guardian-protected"
      values   = ["true"]
    }
  }

  # NOTE: intentionally NO rds:* destructive actions and NO ec2:TerminateInstances.
}

resource "aws_iam_role" "remediation" {
  count              = var.enable_remediation_role ? 1 : 0
  name               = "${var.name_prefix}-remediation-role"
  assume_role_policy = data.aws_iam_policy_document.remediation_assume.json
}

resource "aws_iam_policy" "remediation" {
  count       = var.enable_remediation_role ? 1 : 0
  name        = "${var.name_prefix}-remediation"
  description = "Narrow destructive permissions for approved Cloud Cost Guardian cleanups (human use only)"
  policy      = data.aws_iam_policy_document.remediation.json
}

resource "aws_iam_role_policy_attachment" "remediation" {
  count      = var.enable_remediation_role ? 1 : 0
  role       = aws_iam_role.remediation[0].name
  policy_arn = aws_iam_policy.remediation[0].arn
}
