# Deployment (optional)

> The required project is local and free. Everything on this page creates real AWS resources
> and **may incur charges**. Nothing here runs automatically.

## What gets deployed

| Resource | Purpose |
|---|---|
| Lambda `cloud-cost-guardian-scanner` (arm64, python3.12, 256 MB, 5 min) | runs `lambda_handler.handler` — a read-only scan |
| EventBridge rule `rate(7 days)` | triggers the Lambda |
| SNS topic (+ optional e-mail subscription) | receives the Markdown report |
| CloudWatch log group (14-day retention) | Lambda logs (JSON) |
| IAM role + `scan-readonly` policy | Lambda execution |
| IAM role + `remediation` policy (only if `enable_remediation_role=true`) | MFA-gated, human-assumed, never attached to the Lambda |

## Prerequisites

* Terraform ≥ 1.5, AWS CLI, Python 3.12 (for building the Lambda zip).
* AWS credentials with permission to create the above (an admin-ish deployer role; the *scanner* itself is least-privilege).

## Steps

```powershell
# 1. build the Lambda package (vendors pydantic; boto3 is provided by the runtime)
.\scripts\build_lambda_package.ps1          # Linux/macOS: bash scripts/build_lambda_package.sh

# 2. configure
cd terraform
Copy-Item terraform.tfvars.example terraform.tfvars   # edit; git-ignored

# 3. plan / apply
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan
terraform apply

# 4. confirm the e-mail subscription if you set notification_email

# 5. test once without waiting a week
aws lambda invoke --function-name cloud-cost-guardian-scanner out.json; Get-Content out.json

# 6. tear down when done
terraform destroy
```

## GitHub Actions (`deploy.yml`)

1. Create an IAM OIDC identity provider for `token.actions.githubusercontent.com`.
2. Create a role trusting it with condition `token.actions.githubusercontent.com:sub` =
   `repo:<owner>/<repo>:environment:aws-optional`; attach deployer permissions.
3. Create the GitHub environment `aws-optional` with required reviewers.
4. Set repository variable `AWS_ROLE_TO_ASSUME` (and optionally `AWS_REGION`).
5. Run the workflow manually: `plan` first; `apply`/`destroy` require typing the word in the confirm box.

## Notes

* Lambda's only writable path is its temp directory; the handler points artifacts there. Reports
  are delivered via SNS, not persisted.
* The Lambda's environment contains only non-secret `CCG_*` values. If you add Slack, follow
  `terraform/secrets.tf` (SSM SecureString, read at runtime).
* Remote state is not configured on purpose; if you use S3 state, enable encryption and locking.
