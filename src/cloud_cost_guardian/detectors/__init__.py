"""Detectors — each turns part of an Inventory into Findings."""

from cloud_cost_guardian.detectors.base import Detector, DetectorContext
from cloud_cost_guardian.detectors.ebs_detector import EBSDetector
from cloud_cost_guardian.detectors.ec2_detector import EC2Detector
from cloud_cost_guardian.detectors.eip_detector import EIPDetector
from cloud_cost_guardian.detectors.rds_detector import RDSDetector
from cloud_cost_guardian.detectors.snapshot_detector import SnapshotDetector

ALL_DETECTORS: tuple[type[Detector], ...] = (
    EBSDetector,
    EC2Detector,
    EIPDetector,
    RDSDetector,
    SnapshotDetector,
)

__all__ = [
    "ALL_DETECTORS",
    "Detector",
    "DetectorContext",
    "EBSDetector",
    "EC2Detector",
    "EIPDetector",
    "RDSDetector",
    "SnapshotDetector",
]
