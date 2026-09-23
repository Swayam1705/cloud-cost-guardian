# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | yes |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's *Report a vulnerability* (Security → Advisories → New draft advisory) on this
repository. Include reproduction steps and impact. You will receive an acknowledgement within a few
days and a fix or mitigation plan as soon as practical.

## Scope

Of particular interest:

* Any way to make the tool delete or modify a resource without passing all gates described in
  [docs/cleanup-safety.md](docs/cleanup-safety.md) (protection, policy, approval, re-verification).
* Any way a protected resource (`cost-guardian-protected=true` or configured tags) can be remediated.
* Any path that touches RDS destructively.
* Leakage of credentials or webhook URLs through logs, reports, artifacts, error messages or the Docker image.
* Over-broad permissions in `terraform/iam.tf`.

## Design notes

See [docs/security.md](docs/security.md).
