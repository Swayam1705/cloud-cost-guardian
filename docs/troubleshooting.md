# Troubleshooting

Each entry: **Problem → Cause → Diagnose → Fix → Verify.**

---

## Python / local

### `python` is not recognized (Windows)
* **Cause:** Python not installed or not on PATH.
* **Diagnose:** `py --version`, `where.exe python`.
* **Fix:** Install from python.org with "Add python.exe to PATH", or use `py -m venv .venv`.
* **Verify:** `python --version` prints 3.10+.

### `Activate.ps1 cannot be loaded because running scripts is disabled`
* **Cause:** PowerShell execution policy.
* **Fix:** `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` then re-run `.venv\Scripts\Activate.ps1`.
* **Verify:** prompt shows `(.venv)`.

### `ModuleNotFoundError: No module named 'cloud_cost_guardian'`
* **Cause:** venv not activated, or `pip install -r requirements.txt` (which installs the package with `-e .`) not run.
* **Diagnose:** `pip show cloud-cost-guardian`.
* **Fix:** activate the venv; `pip install -r requirements.txt`.
* **Verify:** `python -m cloud_cost_guardian.cli.main version`.

### `configuration error: invalid configuration: ...`
* **Cause:** an out-of-range `CCG_*` value in the environment or `.env`.
* **Diagnose:** the message names the field; `Get-ChildItem Env:CCG_*`.
* **Fix:** correct or unset the variable. Rules: thresholds 0–100, ages ≥ 0, `CCG_MODE=local` needs `CCG_AWS_ENDPOINT_URL`, `slack` needs a webhook, `sns` needs a topic ARN.
* **Verify:** `ccg validate-config` prints `Configuration OK`.

### `error: no report found at artifacts/reports/latest.json`
* **Cause:** `report` / `cleanup` run before any scan, or a different `CCG_ARTIFACTS_DIR`.
* **Fix:** `ccg scan --mode demo` first.

### `Resource 'x' is not in the latest report`
* **Cause:** typo, or the resource was already remediated / re-scanned away.
* **Fix:** `ccg report` to list current IDs; copy exactly.

### pip dependency resolution errors / very old pip
* **Fix:** `python -m pip install --upgrade pip` then reinstall. If behind a proxy set `HTTPS_PROXY`.

### `pip-audit` reports vulnerabilities in packages the project does not use
* **Cause:** you ran it in a shared/global interpreter with other packages installed.
* **Fix:** run it inside the project venv (`scripts/validate.ps1` does). Genuine findings in `boto3`/`pydantic`: upgrade within the constraints in `pyproject.toml` and open a PR.

---

## Git / GitHub

### `fatal: remote origin already exists`
* **Diagnose:** `git remote -v`.
* **Fix:** `git remote set-url origin <URL>` (update) or `git remote remove origin` then `git remote add origin <URL>`.
* **Verify:** `git remote -v` shows the intended URL.

### `! [rejected] main -> main (non-fast-forward)`
* **Cause:** the remote has commits you do not have (e.g. a README created on GitHub).
* **Fix (safe):** `git pull --rebase origin main`, resolve conflicts if any, `git push -u origin main`.
* **Avoid:** `git push --force` on a shared branch. If you *must* overwrite your own brand-new repo, prefer `git push --force-with-lease`.

### Authentication failed / `Support for password authentication was removed`
* **Cause:** GitHub no longer accepts account passwords over HTTPS.
* **Fix:** use **SSH** (`ssh-keygen -t ed25519`, add the public key in GitHub → Settings → SSH keys, remote `git@github.com:owner/repo.git`) or a **fine-grained personal access token** as the HTTPS password (Windows Git Credential Manager will prompt once), or `gh auth login`.
* **Verify:** `ssh -T git@github.com` or `git ls-remote origin`.

### Pushed to the wrong branch / branch is `master`
* **Diagnose:** `git branch --show-current`, `git log --oneline -5`.
* **Fix:** `git branch -M main` then `git push -u origin main`; delete the stray remote branch with `git push origin --delete <name>` if needed.

### Push rejected (other reasons)
* **Diagnose:** read the full message; `GIT_CURL_VERBOSE=1 git push` for HTTP details; check branch protection rules on GitHub.
* **Typical fixes:** open a PR instead of pushing to a protected branch; sign commits if required.

### GitHub push protection: "secret detected"
* **Cause:** a token/key is in a commit (possibly an old one).
* **Fix:** 1) **rotate/revoke the secret immediately** (it is compromised the moment it left your machine); 2) remove it from history — for the last commit `git rm --cached <file>; git commit --amend`; for older commits use `git filter-repo --path <file> --invert-paths` (install: `pip install git-filter-repo`); 3) add the file to `.gitignore`; 4) push again.
* **Verify:** `git log -p | Select-String "<secret-prefix>"` returns nothing; gitleaks CI job passes.

### Large file rejected (>100 MB)
* **Diagnose:** `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | Sort-Object { [int]($_ -split ' ')[2] } -Descending | Select-Object -First 10`.
* **Fix:** remove it from history with `git filter-repo --path <file> --invert-paths`; add to `.gitignore`. Typical culprits here: `lambda_package.zip`, `.venv`, `artifacts/`.

### Merge conflict
* **Fix:** `git status` lists conflicted files; edit and remove `<<<<<<<`/`>>>>>>>` markers; `git add <file>`; `git rebase --continue` (or `git commit` for merges). To abort: `git rebase --abort` / `git merge --abort`.
* **Verify:** `pytest` passes after resolution.

---

## Docker

### `docker: command not found` / `Cannot connect to the Docker daemon`
* **Fix:** install/start Docker Desktop (Windows: ensure WSL 2 backend is enabled).

### Build fails downloading `python:3.12-slim`
* **Cause:** no network / proxy / Docker Hub rate limit.
* **Fix:** retry; configure proxy in Docker Desktop settings; `docker login` raises the anonymous pull limit (free account).

### `PermissionError` writing `/app/artifacts` when mounting a volume
* **Cause:** the container runs as UID 10001; the host directory is owned by someone else.
* **Fix:** create the directory first and make it writable (`chmod 777 artifacts data` on Linux, or use a named volume). On Docker Desktop for Windows/macOS this is usually not an issue.

### Container exits immediately with usage text
* **Cause:** the entrypoint is `ccg`; you passed no/invalid subcommand.
* **Fix:** `docker run --rm cloud-cost-guardian scan --mode demo`.

### `docker compose up` re-runs the scan every time
* **Expected:** the service is a one-shot job. Use `docker compose run --rm ccg <command>` for other commands.

---

## Terraform

### `Error: Failed to query available provider packages` / `Could not retrieve the list of available versions`
* **Cause:** no network or proxy blocking `registry.terraform.io`.
* **Fix:** retry; set `HTTPS_PROXY`; or use a provider mirror (`terraform providers mirror`).

### `terraform validate` fails with `Invalid function argument: filebase64sha256`
* **Cause:** `lambda_package.zip` does not exist.
* **Fix:** build it (`scripts/build_lambda_package.ps1`) or `touch ../lambda_package.zip` for validate-only.

### `terraform fmt -check` exits 3
* **Cause:** formatting drift.
* **Fix:** `terraform fmt -recursive`; commit.

### `AccessDenied` / `UnauthorizedOperation` during `apply`
* **Diagnose:** the error names the action (e.g. `iam:CreateRole`). `aws sts get-caller-identity` shows who you are.
* **Fix:** deploy with a principal that has those permissions; the *scanner* role stays least-privilege regardless.

### Lambda `Runtime.ImportModuleError: No module named 'pydantic_core._pydantic_core'`
* **Cause:** zip built for the wrong architecture/Python.
* **Fix:** rebuild with the provided script (targets `manylinux2014_aarch64`, cp312) and keep `architectures = ["arm64"]`, `runtime = "python3.12"` in sync.

### Lambda `Unable to import module 'cloud_cost_guardian.lambda_handler'`
* **Cause:** zip packaged with an extra top-level folder.
* **Diagnose:** `unzip -l lambda_package.zip | head` — `cloud_cost_guardian/` must be at the root.
* **Fix:** rebuild with the script.

### EventBridge rule exists but Lambda never runs
* **Diagnose:** `aws events list-targets-by-rule --rule cloud-cost-guardian-schedule`; `aws lambda get-policy --function-name cloud-cost-guardian-scanner` must contain the `events.amazonaws.com` statement.
* **Fix:** `terraform apply` again (creates `aws_lambda_permission.allow_eventbridge`); wait one schedule period or invoke manually.

### SNS `AuthorizationError` when publishing
* **Cause:** topic policy or role policy missing.
* **Fix:** both are managed in `sns.tf`/`iam.tf`; re-apply. Confirm the e-mail subscription (check spam).

### Slack webhook returns 403 / `NotificationError: Slack webhook returned HTTP 403`
* **Cause:** revoked/incorrect webhook or workspace policy.
* **Fix:** regenerate the webhook in Slack; set `CCG_SLACK_WEBHOOK_URL` via environment (never commit). The tool never prints the URL — compare its last 4 characters manually.

---

## GitHub Actions

### `tests` job fails only on Windows
* **Diagnose:** open the job log; usually path separators or line endings. Run `scripts/smoke_test.ps1` locally in PowerShell.

### `security / Trivy` fails on a base-image CVE
* **Cause:** new CVE in `python:3.12-slim`. `ignore-unfixed: true` already skips those without a fix.
* **Fix:** rebuild (pulls the patched base) or bump the tag; do not lower the severity threshold.

### `security / Checkov` fails
* **Fix:** read the check ID; fix the Terraform or, if it is a genuine cost/complexity trade-off, add it to `skip_check` **and** document it in `docs/security.md`.

### `deploy` fails: `Repository variable AWS_ROLE_TO_ASSUME is not set`
* **Fix:** follow [deployment.md](deployment.md) § GitHub Actions.

---

## AWS read-only mode

### `NoCredentials: no AWS credentials found in the credential chain`
* **Fix:** `aws configure sso` / `aws configure --profile x` and `$env:AWS_PROFILE = "x"`, or export the three env vars for the session.

### `ec2.describe_volumes failed [UnauthorizedOperation]`
* **Fix:** attach the read-only policy from [aws-permissions.md](aws-permissions.md). The scan continues with the other detectors and lists the failure under *Warnings*.

### `Throttling` warnings
* **Cause:** many running instances → many CloudWatch calls. boto3 adaptive retries handle bursts.
* **Fix:** rerun; or raise `CCG_AWS_MAX_RETRIES`; or disable a detector (`CCG_EC2_ENABLED=false`) for a quick inventory-only pass.

### `endpoint unreachable or timed out`
* **Cause:** network/VPN, wrong `CCG_AWS_ENDPOINT_URL` in local mode.
* **Fix:** check connectivity; raise `CCG_AWS_CONNECT_TIMEOUT`/`CCG_AWS_READ_TIMEOUT`.
