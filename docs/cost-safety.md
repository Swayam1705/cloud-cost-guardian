# Cost safety — how to keep this at ₹0 / $0

## What is free, always

Everything in the required workflow runs on your machine with no external service:

| Action | Network calls | Cost |
|---|---|---|
| `ccg scan --mode demo` | none | $0 |
| `ccg report`, `ccg cleanup --dry-run`, `ccg cleanup --resource … --approve` (demo) | none | $0 |
| `pytest` (including moto integration tests) | none | $0 |
| `docker build` / `docker run … scan --mode demo` | pulls `python:3.12-slim` from Docker Hub once | $0 |
| GitHub Actions CI on a **public** repository | GitHub-hosted runners | $0 (public repos have free minutes) |
| `terraform fmt` / `validate` | provider download only | $0 |

No component requires a credit card, a trial, an API key or a paid tier.

## What needs an AWS account (still not billed for the calls themselves)

`ccg scan --mode aws` performs only `ec2:Describe*`, `rds:DescribeDBInstances` and
`cloudwatch:GetMetricStatistics`. AWS does not charge for these API requests. However:

* You need an AWS account, which requires a payment method at sign-up. That is an AWS policy,
  not a project requirement — the project is complete without it.
* CloudWatch `GetMetricStatistics` has a request quota, not a price; the scanner makes one call per
  running instance and per database.

## What can cost money — and is therefore optional and never automatic

| Thing | Why it can cost | How the project prevents accidents |
|---|---|---|
| Terraform deployment (Lambda, EventBridge, SNS, CloudWatch Logs) | Real AWS resources; free-tier allowances expire, pricing changes | Lives in `terraform/`, never applied by CI on push, `deploy.yml` is manual with typed confirmation, docs say "may incur charges" everywhere |
| Slack / SNS notifications | SNS e-mail is free at small volume but is still a billable service | Default provider is `mock` (writes a file); Slack/SNS need explicit configuration |
| LocalStack Pro, paid observability, hosted dashboards | Paid | Not used. LocalStack *Community* / moto are optional and free |

## Guaranteed-₹0 checklist

1. Never run `terraform apply`. (`plan` and `validate` are fine.)
2. Keep `CCG_NOTIFICATION_PROVIDER=mock` (the default).
3. Do not create AWS resources "to test the scanner" — use demo mode or the moto tests.
4. If you use `--mode aws`, use a read-only IAM principal (see `aws-permissions.md`) so the tool
   *cannot* create anything even by mistake.
5. Keep the GitHub repository public if you rely on free Actions minutes.

## Why the scanner itself cannot create cost

The AWS layer contains exactly four mutating functions — `delete_volume`, `release_address`,
`delete_snapshot`, `stop_instance` — all of which *reduce* resources. There is no `create_*`,
`run_instances`, `allocate_address` or `create_db_instance` anywhere in `src/`. You can verify:

```powershell
Select-String -Path src -Pattern "create_|run_instances|allocate_address" -Recurse
```
