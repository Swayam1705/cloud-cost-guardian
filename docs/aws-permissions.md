# AWS permissions

## Read-only scan policy (all you need for `--mode aws`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeEC2Resources",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeAddresses",
        "ec2:DescribeSnapshots"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DescribeRDSInstances",
      "Effect": "Allow",
      "Action": "rds:DescribeDBInstances",
      "Resource": "arn:aws:rds:*:<ACCOUNT_ID>:db:*"
    },
    {
      "Sid": "ReadUtilizationMetrics",
      "Effect": "Allow",
      "Action": "cloudwatch:GetMetricStatistics",
      "Resource": "*"
    }
  ]
}
```

| Permission | Used by | Why |
|---|---|---|
| `ec2:DescribeVolumes` | EBS detector, EBS re-fetch | attachment state, size, type, age, tags |
| `ec2:DescribeInstances` | EC2 detector | state, type, launch time, tags |
| `ec2:DescribeAddresses` | EIP detector, EIP re-fetch | association state, tags |
| `ec2:DescribeSnapshots` (`OwnerIds=self`) | snapshot detector, re-fetch | age, size, state, tags |
| `rds:DescribeDBInstances` | RDS detector | class, engine, status, Multi-AZ, tags (returned as `TagList`) |
| `cloudwatch:GetMetricStatistics` | EC2 & RDS detectors | CPU evidence |

EC2 `Describe*` and `cloudwatch:GetMetricStatistics` do not support resource-level ARNs, hence `"Resource": "*"`; `rds:DescribeDBInstances` does, so it is scoped to your account.
Alternatively attach the AWS-managed `ReadOnlyAccess` policy for a quick start; the custom policy above is tighter.

## Remediation policy (separate; only if you will run real cleanups)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DeleteUnattachedVolumes",
      "Effect": "Allow",
      "Action": "ec2:DeleteVolume",
      "Resource": "arn:aws:ec2:*:*:volume/*",
      "Condition": { "StringNotEqualsIgnoreCase": { "aws:ResourceTag/cost-guardian-protected": "true" } }
    },
    {
      "Sid": "ReleaseElasticIPs",
      "Effect": "Allow",
      "Action": "ec2:ReleaseAddress",
      "Resource": "arn:aws:ec2:*:*:elastic-ip/*",
      "Condition": { "StringNotEqualsIgnoreCase": { "aws:ResourceTag/cost-guardian-protected": "true" } }
    },
    {
      "Sid": "DeleteOldSnapshots",
      "Effect": "Allow",
      "Action": "ec2:DeleteSnapshot",
      "Resource": "arn:aws:ec2:*::snapshot/*",
      "Condition": { "StringNotEqualsIgnoreCase": { "aws:ResourceTag/cost-guardian-protected": "true" } }
    }
  ]
}
```

Attach this to a **different** principal than the scanner (Terraform creates an MFA-gated role for it).
Deliberately absent: `rds:*`, `ec2:TerminateInstances`, `ec2:StopInstances`.

## Safe local credential setup

Never put keys in files inside the repo. Use one of:

```powershell
# 1. AWS SSO / Identity Center (best)
aws configure sso --profile readonly
$env:AWS_PROFILE = "readonly"

# 2. Named profile with long-lived keys stored in %USERPROFILE%\.aws\credentials (outside the repo)
aws configure --profile readonly

# 3. Environment variables for one shell session only
$env:AWS_ACCESS_KEY_ID = "..."; $env:AWS_SECRET_ACCESS_KEY = "..."; $env:AWS_SESSION_TOKEN = "..."
```

Then `ccg scan --mode aws --region <region>`. The tool reads the standard boto3 credential chain; it
never asks for or stores credentials itself.

## GitHub Actions

`deploy.yml` uses OpenID Connect: create an IAM role trusting `token.actions.githubusercontent.com`
with a condition on your repository (`repo:<owner>/<repo>:*`), attach the permissions Terraform needs,
and store the role ARN as repository **variable** `AWS_ROLE_TO_ASSUME`. No long-lived keys are stored in GitHub.
