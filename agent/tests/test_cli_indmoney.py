from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import cli


class TestCliIndmoney:
    def test_bare_indmoney_is_usage_error(self) -> None:
        """`vibe-trading indmoney` with no subcommand exits with usage error."""
        assert cli.main(["indmoney"]) == cli.EXIT_USAGE_ERROR

    def test_status_no_token(self) -> None:
        """`indmoney status` reports a usage error when no token is cached."""
        with patch("src.integrations.indmoney.auth.TokenCache") as cache_cls:
            cache_cls.return_value.load.return_value = None
            assert cli.cmd_indmoney_status() == cli.EXIT_USAGE_ERROR

    def test_status_with_token(self) -> None:
        """`indmoney status` succeeds and prints state when a token exists."""
        token = SimpleNamespace(
            account_id="acct-1",
            expires_at="1781277769",
            is_expired=lambda: False,
        )
        with patch("src.integrations.indmoney.auth.TokenCache") as cache_cls:
            cache_cls.return_value.load.return_value = token
            assert cli.cmd_indmoney_status() == cli.EXIT_SUCCESS

    def test_status_routes_through_main(self) -> None:
        """The `status` subcommand dispatches to cmd_indmoney_status."""
        with patch("cli._legacy.cmd_indmoney_status", return_value=cli.EXIT_SUCCESS) as fn:
            assert cli.main(["indmoney", "status"]) == cli.EXIT_SUCCESS
            fn.assert_called_once_with()

    def test_login_routes_to_helper_script(self) -> None:
        """`indmoney login` shells out to scripts/indmoney_oauth.py."""
        with patch("subprocess.call", return_value=0) as call:
            assert cli.main(["indmoney", "login"]) == cli.EXIT_SUCCESS
            call.assert_called_once()
            invoked = call.call_args.args[0]
            assert str(invoked[-1]).endswith("scripts/indmoney_oauth.py")
