"""Dedicated adversarial security and policy isolation tests."""

from __future__ import annotations

import pytest

from cloud_cost_guardian.utils.security import (
    assert_safe_remediation_action,
    is_resource_protected,
    sanitize_resource_id,
    validate_exact_resource_id,
)


class TestSecurityUtilities:
    @pytest.mark.parametrize(
        "malicious_id",
        [
            "../../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\cmd.exe",
            "i-12345/../../../var/log",
            "vol-abc\\x00.json",
            "i-12345; rm -rf /",
            "i-12345`whoami`",
            "i-12345$(id)",
            "i-12345|cat /etc/shadow",
        ],
    )
    def test_path_traversal_sanitization(self, malicious_id: str) -> None:
        sanitized = sanitize_resource_id(malicious_id)
        assert ".." not in sanitized
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert ";" not in sanitized
        assert "`" not in sanitized

    def test_empty_resource_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            sanitize_resource_id("")
        with pytest.raises(ValueError):
            sanitize_resource_id("   ")

    def test_valid_aws_ids_remain_safe(self) -> None:
        valid_ids = ["i-0123456789abcdef0", "vol-0987654321fedcba0", "snap-11223344556677889"]
        for rid in valid_ids:
            assert sanitize_resource_id(rid) == rid

    @pytest.mark.parametrize(
        "tags,expected",
        [
            ({"protected": "true"}, True),
            ({"Protected": "True"}, True),
            ({"PROTECTED": "TRUE"}, True),
            ({"cloud-cost-guardian:protected": "1"}, True),
            ({"ccg:protected": "yes"}, True),
            ({"do-not-delete": "enabled"}, True),
            ({"Environment": "production"}, False),
            ({"protected": "false"}, False),
            ({}, False),
            (None, False),
        ],
    )
    def test_protection_tags_evaluation(self, tags: dict | None, expected: bool) -> None:
        assert is_resource_protected(tags) is expected

    def test_rds_destructive_action_guard(self) -> None:
        assert assert_safe_remediation_action("rds", "delete_db_instance") == "recommend_downsize"
        assert assert_safe_remediation_action("rds_cluster", "terminate") == "recommend_downsize"
        assert assert_safe_remediation_action("ec2", "stop_instance") == "stop_instance"

    def test_exact_resource_id_matching(self) -> None:
        assert validate_exact_resource_id("i-12345", "i-12345") is True
        assert validate_exact_resource_id("i-12345", "i-12345-extra") is False
        assert validate_exact_resource_id("i-12345", "i-123") is False
