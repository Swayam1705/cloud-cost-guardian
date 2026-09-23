## What & why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `ruff check .` / `ruff format --check .` / `mypy` / `pytest` pass locally
- [ ] New behaviour has tests; new safety rule has a **negative** test
- [ ] No new required service, credential or paid dependency
- [ ] No destructive path bypasses `CleanupService`; RDS remains recommendation-only
- [ ] Docs updated (README / docs/*) if user-facing
- [ ] `demo/expected_report.json` regenerated if fixtures or policy changed
