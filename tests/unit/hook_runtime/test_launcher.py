"""Unit tests for hook runtime daemon CLI entry point. [OMN-5307]"""

import pytest


@pytest.mark.unit
def test_cli_entry_point_exists() -> None:
    """Verify python -m omniclaude.hook_runtime is importable and has main()."""
    import omniclaude.hook_runtime.__main__ as entrypoint

    assert hasattr(entrypoint, "main")
    assert callable(entrypoint.main)


@pytest.mark.unit
def test_main_accepts_start_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify start subcommand is parseable without executing."""

    import omniclaude.hook_runtime.__main__ as entrypoint

    # Parse args without executing
    parser = entrypoint._build_parser()
    args = parser.parse_args(["start", "--socket-path", "/tmp/test.sock"])
    assert args.command == "start"
    assert args.socket_path == "/tmp/test.sock"


@pytest.mark.unit
def test_main_accepts_stop_subcommand() -> None:
    """Verify stop subcommand is parseable."""
    import omniclaude.hook_runtime.__main__ as entrypoint

    parser = entrypoint._build_parser()
    args = parser.parse_args(["stop"])
    assert args.command == "stop"


@pytest.mark.unit
def test_main_accepts_status_subcommand() -> None:
    """Verify status subcommand is parseable."""
    import omniclaude.hook_runtime.__main__ as entrypoint

    parser = entrypoint._build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"
