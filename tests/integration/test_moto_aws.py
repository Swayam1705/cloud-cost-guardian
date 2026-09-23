"""Integration tests against moto (in-process AWS simulation). No network, no cost."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from cloud_cost_guardian.app import Application
from cloud_cost_guardian.aws.client_factory import AWSClientFactory
from cloud_cost_guardian.aws.errors import AWSAccessDeniedError, translate_client_error
from cloud_cost_guardian.aws.inventory_source import AWSInventorySource
from cloud_cost_guardian.config import Mode, Settings
from cloud_cost_guardian.models.resources import ResourceType
from cloud_cost_guardian.policies.thresholds import Thresholds
from cloud_cost_guardian.remediation.approval import ExplicitApproval

pytestmark = pytest.mark.integration
REGION = "us-east-1"


@pytest.fixture
def aws_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode=Mode.AWS,
        aws_region=REGION,
        artifacts_dir=tmp_path / "artifacts",
        data_dir=tmp_path / "data",
        protected_tags="cost-guardian-protected=true",
        _env_file=None,  # type: ignore[call-arg]
    )


def _seed() -> dict[str, str]:
    ec2 = boto3.client("ec2", region_name=REGION)
    rds = boto3.client("rds", region_name=REGION)
    az = f"{REGION}a"
    unattached = ec2.create_volume(AvailabilityZone=az, Size=100, VolumeType="gp3")["VolumeId"]
    protected = ec2.create_volume(
        AvailabilityZone=az,
        Size=50,
        VolumeType="gp3",
        TagSpecifications=[
            {
                "ResourceType": "volume",
                "Tags": [{"Key": "cost-guardian-protected", "Value": "true"}],
            }
        ],
    )["VolumeId"]
    ami = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    instance_id = ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1, InstanceType="t3.micro")[
        "Instances"
    ][0]["InstanceId"]
    attached = ec2.create_volume(AvailabilityZone=az, Size=8)["VolumeId"]
    ec2.attach_volume(VolumeId=attached, InstanceId=instance_id, Device="/dev/sdf")
    eip_alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    snap = ec2.create_snapshot(VolumeId=unattached, Description="old")["SnapshotId"]
    rds.create_db_instance(
        DBInstanceIdentifier="db1",
        DBInstanceClass="db.t3.small",
        Engine="postgres",
        AllocatedStorage=20,
    )
    return {
        "unattached": unattached,
        "protected": protected,
        "attached": attached,
        "instance": instance_id,
        "eip": eip_alloc,
        "snap": snap,
    }


@mock_aws
def test_aws_inventory_source_reads_everything(aws_settings: Settings) -> None:
    ids = _seed()
    # moto creates resources "now"; pretend the scan happens far in the future so age gates pass.
    future = datetime.now(timezone.utc) + timedelta(days=200)
    source = AWSInventorySource(AWSClientFactory(aws_settings), Thresholds(), now=future)
    inv = source.load()
    assert {v.resource_id for v in inv.volumes} >= {
        ids["unattached"],
        ids["protected"],
        ids["attached"],
    }
    assert next(v for v in inv.volumes if v.resource_id == ids["attached"]).is_attached
    assert [e.resource_id for e in inv.elastic_ips] == [ids["eip"]]
    # moto ignores OwnerIds=["self"] and also returns its built-in public AMI snapshots,
    # so assert containment rather than equality (real AWS returns only owned snapshots).
    assert ids["snap"] in {s.resource_id for s in inv.snapshots}
    assert [d.resource_id for d in inv.db_instances] == ["db1"]
    assert ids["instance"] in {i.resource_id for i in inv.instances}
    assert inv.source_errors == ()
    # CloudWatch in moto returns no datapoints -> series exists but is empty -> no EC2/RDS findings
    assert inv.metrics[ids["instance"]].sample_count == 0


@mock_aws
def test_aws_mode_scan_and_refetch(aws_settings: Settings) -> None:
    ids = _seed()
    future = datetime.now(timezone.utc) + timedelta(days=200)
    app = Application.build(aws_settings, now=future)
    report = app.scan_service(None).run(notify=False).report
    by_id = {f.resource_id: f for f in report.findings}
    assert by_id[ids["unattached"]].cleanup_eligible
    assert by_id[ids["protected"]].protected and not by_id[ids["protected"]].cleanup_eligible
    assert by_id[ids["eip"]].cleanup_eligible
    assert by_id[ids["snap"]].cleanup_eligible
    assert ids["attached"] not in by_id
    assert report.mode == "aws"

    single = app.source.refetch(ResourceType.EBS_VOLUME, ids["unattached"])
    assert single.resource_count == 1
    gone = app.source.refetch(ResourceType.EBS_VOLUME, "vol-0123456789abcdef0")
    assert gone.resource_count == 0


@mock_aws
def test_aws_cleanup_without_destructive_flag_is_blocked(aws_settings: Settings) -> None:
    ids = _seed()
    future = datetime.now(timezone.utc) + timedelta(days=200)
    app = Application.build(aws_settings, now=future)
    report = app.scan_service(None).run(notify=False).report
    target = next(f for f in report.findings if f.resource_id == ids["unattached"])
    svc = app.cleanup_service(ExplicitApproval(ids["unattached"]), allow_aws_destructive=False)
    outcome = svc.remediate(target, report.scan_id)
    assert outcome.status == "blocked" and outcome.stage == "execution"
    ec2 = boto3.client("ec2", region_name=REGION)
    assert ec2.describe_volumes(VolumeIds=[ids["unattached"]])["Volumes"]  # still there


@mock_aws
def test_aws_cleanup_with_explicit_destructive_flag_deletes_and_verifies(
    aws_settings: Settings,
) -> None:
    ids = _seed()
    future = datetime.now(timezone.utc) + timedelta(days=200)
    app = Application.build(aws_settings, now=future)
    report = app.scan_service(None).run(notify=False).report
    target = next(f for f in report.findings if f.resource_id == ids["unattached"])
    svc = app.cleanup_service(ExplicitApproval(ids["unattached"]), allow_aws_destructive=True)
    outcome = svc.remediate(target, report.scan_id)
    assert outcome.remediated, outcome.detail
    assert "no longer present" in outcome.detail
    ec2 = boto3.client("ec2", region_name=REGION)
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        ec2.describe_volumes(VolumeIds=[ids["unattached"]])
    # protected volume still exists and is still blocked
    prot = next(f for f in report.findings if f.resource_id == ids["protected"])
    assert svc.remediate(prot, report.scan_id).stage == "protection"
    assert ec2.describe_volumes(VolumeIds=[ids["protected"]])["Volumes"]


@mock_aws
def test_resource_changed_after_scan_in_aws(aws_settings: Settings) -> None:
    ids = _seed()
    future = datetime.now(timezone.utc) + timedelta(days=200)
    app = Application.build(aws_settings, now=future)
    report = app.scan_service(None).run(notify=False).report
    target = next(f for f in report.findings if f.resource_id == ids["unattached"])
    # Someone attaches the volume between scan and cleanup.
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.attach_volume(VolumeId=ids["unattached"], InstanceId=ids["instance"], Device="/dev/sdg")
    svc = app.cleanup_service(ExplicitApproval(ids["unattached"]), allow_aws_destructive=True)
    outcome = svc.remediate(target, report.scan_id)
    assert outcome.status == "blocked" and outcome.stage == "verification"
    assert ec2.describe_volumes(VolumeIds=[ids["unattached"]])["Volumes"]


def test_error_translation() -> None:
    from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

    denied = ClientError(
        {"Error": {"Code": "UnauthorizedOperation", "Message": "nope"}}, "DescribeVolumes"
    )
    err = translate_client_error(denied, "ec2", "describe_volumes")
    assert isinstance(err, AWSAccessDeniedError) and err.code == "UnauthorizedOperation"
    assert isinstance(
        translate_client_error(NoCredentialsError(), "ec2", "x"), AWSAccessDeniedError
    )
    net = translate_client_error(EndpointConnectionError(endpoint_url="http://x"), "ec2", "x")
    assert "unreachable" in str(net)
    throttled = ClientError(
        {"Error": {"Code": "Throttling", "Message": "slow down"}}, "DescribeVolumes"
    )
    assert translate_client_error(throttled, "ec2", "x").code == "Throttling"


@mock_aws
def test_access_denied_is_partial_failure_not_crash(
    aws_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed()
    from botocore.exceptions import ClientError

    from cloud_cost_guardian.aws import rds as rds_mod

    def denied(*a: object, **k: object) -> list[object]:
        raise translate_client_error(
            ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "DescribeDBInstances"),
            "rds",
            "describe_db_instances",
        )

    monkeypatch.setattr(rds_mod, "list_db_instances", denied)
    future = datetime.now(timezone.utc) + timedelta(days=200)
    app = Application.build(aws_settings, now=future)
    report = app.scan_service(None).run(notify=False).report
    assert any("rds" in w and "AccessDenied" in w for w in report.warnings)
    assert report.summary.total_findings > 0
