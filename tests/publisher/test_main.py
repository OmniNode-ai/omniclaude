"""Tests for publisher CLI entry point (__main__.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.publisher.__main__ import _do_stop, _parse_args, main

# Patch target for the local import inside _do_stop
_CONFIG_TARGET = "omniclaude.publisher.publisher_config.PublisherConfig"


class TestParseArgs:
    """Tests for _parse_args."""

    def test_start_requires_kafka_servers(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["start"])

    def test_start_with_kafka_servers(self) -> None:
        args = _parse_args(["start", "--kafka-servers", "localhost:9092"])
        assert args.command == "start"
        assert args.kafka_servers == "localhost:9092"

    def test_start_default_socket_path(self) -> None:
        args = _parse_args(["start", "--kafka-servers", "localhost:9092"])
        expected = str(Path(tempfile.gettempdir()) / "omniclaude-emit.sock")
        assert args.socket_path == expected

    def test_start_custom_socket_path(self) -> None:
        args = _parse_args(
            [
                "start",
                "--kafka-servers",
                "localhost:9092",
                "--socket-path",
                "/custom/path.sock",
            ]
        )
        assert args.socket_path == "/custom/path.sock"

    def test_stop_command(self) -> None:
        args = _parse_args(["stop"])
        assert args.command == "stop"
        assert args.pid_path is None

    def test_stop_custom_pid_path(self) -> None:
        args = _parse_args(["stop", "--pid-path", "/custom/publisher.pid"])
        assert args.command == "stop"
        assert args.pid_path == "/custom/publisher.pid"

    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args([])

    def test_daemonize_flag_removed(self) -> None:
        """--daemonize was removed as dead code."""
        with pytest.raises(SystemExit):
            _parse_args(["start", "--kafka-servers", "localhost:9092", "--daemonize"])


class TestDoStop:
    """Tests for _do_stop."""

    def test_stop_no_pid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(_CONFIG_TARGET, side_effect=Exception("no kafka")):
            with patch("omniclaude.publisher.__main__.tempfile") as mock_tempfile:
                mock_tempfile.gettempdir.return_value = str(tmp_path)
                args = _parse_args(["stop"])
                result = _do_stop(args)
        assert result == 0
        assert "not running" in capsys.readouterr().out

    def test_stop_stale_pid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pid_path = tmp_path / "omniclaude-emit.pid"
        pid_path.write_text("999999999")
        with patch(_CONFIG_TARGET, side_effect=Exception("no kafka")):
            with patch("omniclaude.publisher.__main__.tempfile") as mock_tempfile:
                mock_tempfile.gettempdir.return_value = str(tmp_path)
                args = _parse_args(["stop"])
                result = _do_stop(args)
        assert result == 0
        assert "not found" in capsys.readouterr().out
        assert not pid_path.exists()

    def test_stop_uses_config_pid_path(self, tmp_path: Path) -> None:
        """Stop should respect OMNICLAUDE_PUBLISHER_PID_PATH via config."""
        custom_pid = tmp_path / "custom.pid"
        custom_pid.write_text("999999999")

        mock_config = type("MockConfig", (), {"pid_path": custom_pid})()
        with patch(_CONFIG_TARGET, return_value=mock_config):
            args = _parse_args(["stop"])
            result = _do_stop(args)
        assert result == 0
        assert not custom_pid.exists()

    def test_stop_cli_pid_path_overrides_config(self, tmp_path: Path) -> None:
        """--pid-path CLI arg should take priority over config."""
        cli_pid = tmp_path / "cli.pid"
        cli_pid.write_text("999999999")

        # Config points to a different path — should be ignored
        config_pid = tmp_path / "config.pid"
        config_pid.write_text("111111111")
        mock_config = type("MockConfig", (), {"pid_path": config_pid})()

        with patch(_CONFIG_TARGET, return_value=mock_config):
            args = _parse_args(["stop", "--pid-path", str(cli_pid)])
            result = _do_stop(args)

        assert result == 0
        # CLI pid file was used (stale PID cleaned up)
        assert not cli_pid.exists()
        # Config pid file was NOT touched
        assert config_pid.exists()

    def test_stop_cli_pid_path_no_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--pid-path pointing to missing file should report not running."""
        missing_pid = tmp_path / "missing.pid"
        args = _parse_args(["stop", "--pid-path", str(missing_pid)])
        result = _do_stop(args)
        assert result == 0
        assert "not running" in capsys.readouterr().out


class TestMain:
    """Tests for main() dispatch."""

    def test_main_stop(self, tmp_path: Path) -> None:
        with patch(_CONFIG_TARGET, side_effect=Exception("no kafka")):
            with patch("omniclaude.publisher.__main__.tempfile") as mock_tempfile:
                mock_tempfile.gettempdir.return_value = str(tmp_path)
                result = main(["stop"])
        assert result == 0
