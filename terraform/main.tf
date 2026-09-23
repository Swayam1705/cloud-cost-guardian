# ---------------------------------------------------------------------------
# OPTIONAL / EDUCATIONAL AWS deployment of the scheduled READ-ONLY scanner.
#
# NOT required for the project. The required workflow is 100% local and free.
# Deploying this creates real AWS resources (Lambda, IAM, EventBridge, SNS, Logs).
# At the default weekly schedule usage is tiny, but AWS pricing can change and
# free-tier allowances expire; nothing here is guaranteed to be free forever.
# Run `terraform destroy` when you are done.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.name

  lambda_name = "${var.name_prefix}-scanner"
}
