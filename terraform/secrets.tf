# ---------------------------------------------------------------------------
# Secrets handling.
#
# This deployment needs NO secrets: the Lambda publishes to SNS using its IAM
# role, and SNS delivers by e-mail. There is therefore nothing to store here.
#
# If you later add Slack delivery, do NOT put the webhook in a Terraform
# variable or in Lambda environment variables. Instead:
#   1. create an SSM SecureString parameter out-of-band:
#        aws ssm put-parameter --name /cloud-cost-guardian/slack-webhook \
#            --type SecureString --value "<webhook>"
#   2. grant ssm:GetParameter on that ARN to aws_iam_role.scanner
#   3. read it at runtime in lambda_handler.py
# The parameter itself is intentionally not managed by Terraform so the secret
# never lands in state.
# ---------------------------------------------------------------------------
