"""Tests for the INDMoney error envelope."""

from __future__ import annotations

from src.integrations.indmoney.errors import ErrorKind, build_error


def test_build_error_minimum_fields():
    env = build_error(ErrorKind.UPSTREAM_ERROR, "boom")
    assert env == {
        "ok": False,
        "error_kind": "upstream_error",
        "message": "boom",
        "retry_after_seconds": None,
        "auth_url": None,
    }


def test_build_error_rate_limited_includes_retry_after():
    env = build_error(ErrorKind.RATE_LIMITED, "throttled", retry_after_seconds=42)
    assert env["error_kind"] == "rate_limited"
    assert env["retry_after_seconds"] == 42
    assert env["auth_url"] is None


def test_build_error_needs_auth_includes_url():
    env = build_error(ErrorKind.NEEDS_AUTH, "log in", auth_url="https://example/auth")
    assert env["error_kind"] == "needs_auth"
    assert env["auth_url"] == "https://example/auth"


def test_error_kind_values_match_spec():
    assert ErrorKind.NEEDS_AUTH.value == "needs_auth"
    assert ErrorKind.RATE_LIMITED.value == "rate_limited"
    assert ErrorKind.UPSTREAM_ERROR.value == "upstream_error"
    assert ErrorKind.STALE_TOKEN.value == "stale_token"
    assert ErrorKind.CONFIG_MISSING.value == "config_missing"
