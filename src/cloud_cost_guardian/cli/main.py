"""``ccg`` / ``python -m cloud_cost_guardian.cli.main`` entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cloud_cost_guardian import __version__
from cloud_cost_guardian.app import Application
from cloud_cost_guardian.config import Mode, Settings, load_settings
from cloud_cost_guardian.exceptions import CloudCostGuardianError, ConfigurationError
from cloud_cost_guardian.logging_config import configure_logging, redact
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.reports import ScanReport
from cloud_cost_guardian.remediation.approval import ExplicitApproval, InteractiveApproval
from cloud_cost_guardian.reporting.json_report import load_json
from cloud_cost_guardian.reporting.markdown_report import render_markdown

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3

_CONFIRM_PHRASE = "I understand this deletes real AWS resources"


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _money(v: float) -> str:
    return f"${v:,.2f}"


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ccg",
        description=(
            "Cloud Cost Guardian — find AWS waste locally, remediate only with explicit approval."
        ),
        epilog="Demo mode needs no AWS account: `ccg scan --mode demo`.",
    )
    p.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="override CCG_LOG_LEVEL"
    )
    p.add_argument("--log-format", choices=["text", "json"], help="override CCG_LOG_FORMAT")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("version", help="print version")
    sub.add_parser(
        "validate-config", help="load and print effective configuration (secrets masked)"
    )

    scan = sub.add_parser("scan", help="scan for potentially wasteful resources")
    scan.add_argument(
        "--mode",
        choices=[m.value for m in Mode],
        help="demo (default, no AWS) | local | aws (read-only)",
    )
    scan.add_argument("--region", help="AWS region override")
    scan.add_argument("--no-notify", action="store_true", help="skip the notification step")
    scan.add_argument(
        "--json", action="store_true", help="print the JSON report to stdout instead of a summary"
    )

    rep = sub.add_parser(
        "report", help="print the latest report (from artifacts/reports/latest.json)"
    )
    rep.add_argument("--format", choices=["summary", "markdown", "json"], default="summary")
    rep.add_argument("--path", type=Path, help="report file to read instead of latest.json")

    cl = sub.add_parser("cleanup", help="preview or perform approval-gated remediation")
    cl.add_argument(
        "--mode", choices=[m.value for m in Mode], help="defaults to the mode of the latest report"
    )
    cl.add_argument(
        "--dry-run", action="store_true", help="(default) show candidates, take no action"
    )
    cl.add_argument("--resource", metavar="RESOURCE_ID", help="remediate exactly this resource id")
    cl.add_argument(
        "--approve",
        action="store_true",
        help="non-interactive approval for --resource (CI/scripts)",
    )
    cl.add_argument(
        "--i-understand-this-deletes-real-resources",
        dest="confirm_real",
        action="store_true",
        help="required in aws/local mode for any destructive action",
    )

    demo = sub.add_parser("demo", help="demo helpers")
    demo_sub = demo.add_subparsers(dest="demo_command", metavar="<subcommand>")
    demo_sub.add_parser("reset", help="clear simulated remediation state so the demo starts fresh")
    demo_sub.add_parser("status", help="show simulated remediation state")
    return p


# ---------------------------------------------------------------------------- helpers
def _settings(
    args: argparse.Namespace, *, mode: str | None = None, region: str | None = None
) -> Settings:
    overrides: dict[str, object] = {}
    if mode:
        overrides["mode"] = Mode(mode)
    if region:
        overrides["aws_region"] = region
    if args.log_level:
        overrides["log_level"] = args.log_level
    if args.log_format:
        overrides["log_format"] = args.log_format
    settings = load_settings(**overrides)
    configure_logging(settings.log_level, settings.log_format)
    return settings


def _latest_report(settings: Settings, path: Path | None = None) -> ScanReport:
    target = path or (settings.artifacts_dir / "reports" / "latest.json")
    if not target.exists():
        raise CloudCostGuardianError(
            f"no report found at {target}; run `ccg scan --mode demo` first"
        )
    try:
        return load_json(target)
    except ValueError as exc:
        raise CloudCostGuardianError(f"report at {target} is not valid: {exc}") from exc


def _print_summary(report: ScanReport) -> None:
    s = report.summary
    _out("CLOUD COST GUARDIAN")
    _out("=" * 60)
    _out(f"Scan ID:            {report.scan_id}")
    _out(f"Mode / region:      {report.mode} / {report.region}")
    _out(f"Resources scanned:  {s.resources_scanned}")
    _out(f"Findings:           {s.total_findings}")
    _out()
    _out(f"Estimated monthly waste:     {_money(s.estimated_monthly_waste)}")
    _out(f"Estimated annualized waste:  {_money(s.estimated_annual_waste)}")
    _out(f"Estimated monthly savings:   {_money(s.estimated_monthly_savings)}")
    _out(f"Estimated annualized savings:{_money(s.estimated_annual_savings):>10}")
    _out()
    _out("By category:")
    for cat, n in s.findings_by_category.items():
        _out(f"  {cat:<20} {n}")
    _out("By severity:")
    for sev, n in s.findings_by_severity.items():
        _out(f"  {sev:<20} {n}")
    _out()
    _out(f"Protected findings:  {s.protected_findings}")
    _out(f"Cleanup eligible:    {s.cleanup_eligible}")
    _out(f"Recommendation only: {s.recommendations_only}")
    if report.findings:
        _out()
        _out(
            f"{'STATUS':<18} {'SEV':<6} {'CATEGORY':<18} {'RESOURCE':<26} "
            f"{'MONTHLY':>10} {'SAVINGS':>10}"
        )
        _out("-" * 92)
        for f in report.findings:
            status = (
                "PROTECTED"
                if f.protected
                else ("CLEANUP-ELIGIBLE" if f.cleanup_eligible else "RECOMMENDATION")
            )
            _out(
                f"{status:<18} {f.severity.value:<6} {f.category.value:<18} "
                f"{f.resource_id:<26} {_money(f.estimated_monthly_cost):>10} "
                f"{_money(f.estimated_monthly_savings):>10}"
            )
    if report.warnings:
        _out()
        _out("Warnings:")
        for w in report.warnings:
            _out(f"  - {redact(w)}")
    _out()
    _out(f"Pricing: {report.pricing_catalog} — estimates only, not billing data.")


def _print_candidate(f: Finding) -> None:
    _out("Cleanup candidate:")
    _out(f"  Resource:               {f.resource_id}")
    _out(f"  Type:                   {f.resource_type.value}")
    _out(f"  Region:                 {f.region}")
    age = f.evidence.get("age_days")
    if age is not None:
        _out(f"  Age:                    {age} days")
    _out(f"  Estimated monthly cost: {_money(f.estimated_monthly_cost)}")
    _out(f"  Protected:              {'YES' if f.protected else 'NO'}")
    _out(f"  Policy eligible:        {'YES' if f.cleanup_eligible else 'NO'}")
    _out(f"  Action:                 {f.recommended_action.value}")


# ---------------------------------------------------------------------------- commands
def cmd_version(_: argparse.Namespace) -> int:
    _out(f"cloud-cost-guardian {__version__}")
    return EXIT_OK


def cmd_validate_config(args: argparse.Namespace) -> int:
    settings = _settings(args)
    app = Application.build(settings)  # also validates pricing catalog & protection rules
    _out("Configuration OK")
    for k, v in settings.summary().items():
        _out(f"  {k:<26} {v}")
    _out(f"  {'pricing_catalog_name':<26} {app.pricing.name}")
    return EXIT_OK


def cmd_scan(args: argparse.Namespace) -> int:
    settings = _settings(args, mode=args.mode, region=args.region)
    app = Application.build(settings)
    notifier = None if args.no_notify else app.notifier()
    result = app.scan_service(notifier).run(notify=not args.no_notify)
    if args.json:
        _out(result.report.model_dump_json(indent=2))
    else:
        _print_summary(result.report)
        _out(f"JSON report:     {result.json_path}")
        _out(f"Markdown report: {result.markdown_path}")
        if result.notification:
            state = "sent" if result.notification.delivered else "FAILED"
            _out(
                f"Notification:    {result.notification.provider} {state} — "
                f"{redact(result.notification.detail)}"
            )
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = _latest_report(settings, args.path)
    if args.format == "json":
        _out(report.model_dump_json(indent=2))
    elif args.format == "markdown":
        _out(render_markdown(report))
    else:
        _print_summary(report)
    return EXIT_OK


def cmd_cleanup(args: argparse.Namespace) -> int:
    base = _settings(args)
    report = _latest_report(base)
    mode = args.mode or report.mode
    settings = _settings(args, mode=mode)
    app = Application.build(settings)

    real_mode = settings.mode is not Mode.DEMO
    if args.resource and not args.dry_run and real_mode and not args.confirm_real:
        _out("Refusing to run a destructive action in aws/local mode without")
        _out("  --i-understand-this-deletes-real-resources")
        return EXIT_USAGE

    if not args.resource or args.dry_run:
        # Default path: dry-run of every finding from the latest report.
        service = app.cleanup_service(ExplicitApproval(None))
        outcomes = service.dry_run(list(report.findings), report.scan_id)
        would = [o for o in outcomes if o.status == "dry-run"]
        blocked = [o for o in outcomes if o.status == "blocked"]
        _out(f"DRY RUN — scan {report.scan_id} ({settings.mode.value} mode). No action taken.")
        _out()
        for o in would:
            _print_candidate(o.finding)
            _out()
        _out(f"{len(would)} candidate(s) would be remediated after explicit approval.")
        _out(f"{len(blocked)} finding(s) blocked:")
        for o in blocked:
            _out(f"  - {o.finding.resource_id:<26} [{o.stage}] {o.detail}")
        if args.resource:
            _out()
            _out(f"Dry run only. To remediate: ccg cleanup --resource {args.resource} --approve")
        elif would:
            _out()
            _out("To remediate one resource: ccg cleanup --resource <RESOURCE_ID> --approve")
        return EXIT_OK

    target = next((f for f in report.findings if f.resource_id == args.resource), None)
    if target is None:
        _out(f"Resource {args.resource!r} is not in the latest report. Re-run `ccg scan` first.")
        return EXIT_USAGE
    _print_candidate(target)
    _out()
    approval = ExplicitApproval(args.resource) if args.approve else InteractiveApproval()
    service = app.cleanup_service(approval, allow_aws_destructive=args.confirm_real)
    outcome = service.remediate(target, report.scan_id)
    _out(f"Result: {outcome.status.upper()} at stage '{outcome.stage}' — {redact(outcome.detail)}")
    _out(f"Audit:  {app.artifacts_dir / 'audit' / 'latest-cleanup.json'}")
    if outcome.remediated:
        _out("Re-scan to confirm: ccg scan --mode " + settings.mode.value)
        return EXIT_OK
    return EXIT_BLOCKED if outcome.status == "blocked" else EXIT_ERROR


def cmd_demo(args: argparse.Namespace) -> int:
    settings = _settings(args, mode="demo")
    app = Application.build(settings)
    assert app.demo_state is not None
    if args.demo_command == "reset":
        app.demo_state.reset()
        _out("Demo state reset. Next scan will show all fixture resources again.")
        return EXIT_OK
    if args.demo_command == "status":
        state = app.demo_state.load()
        if not state.remediated:
            _out("No simulated remediations recorded.")
        for r in state.remediated:
            _out(
                f"{r.resource_id:<26} {r.action:<16} {r.remediated_at.isoformat()}  "
                f"(scan {r.scan_id})"
            )
        return EXIT_OK
    _out("usage: ccg demo {reset|status}")
    return EXIT_USAGE


# ---------------------------------------------------------------------------- main
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE
    handlers = {
        "version": cmd_version,
        "validate-config": cmd_validate_config,
        "scan": cmd_scan,
        "report": cmd_report,
        "cleanup": cmd_cleanup,
        "demo": cmd_demo,
    }
    try:
        return handlers[args.command](args)
    except ConfigurationError as exc:
        sys.stderr.write(f"configuration error: {redact(str(exc))}\n")
        return EXIT_USAGE
    except CloudCostGuardianError as exc:
        sys.stderr.write(f"error: {redact(str(exc))}\n")
        return EXIT_ERROR
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
