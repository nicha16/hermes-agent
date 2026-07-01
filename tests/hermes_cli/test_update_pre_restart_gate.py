"""Tests for configured update gates that run before gateway restart.

These gates let a live deployment require narrow regression checks after
``hermes update`` has pulled/reinstalled code but before the freshly updated
code is activated by restarting running gateways.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli import main as hermes_main


def test_pre_gateway_restart_gate_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"updates": {}},
    )

    def unexpected_run(*_args, **_kwargs):  # pragma: no cover - failure path
        raise AssertionError("no update gate command should run by default")

    monkeypatch.setattr(hermes_main.subprocess, "run", unexpected_run)

    assert hermes_main._run_update_pre_gateway_restart_gates(tmp_path) is True


def test_pre_gateway_restart_gate_runs_configured_relative_script(monkeypatch, tmp_path, capsys):
    script = tmp_path / "scripts" / "check_telegram_quote_gate.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\nexit 0\n")

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"updates": {"pre_gateway_restart_gates": ["scripts/check_telegram_quote_gate.sh"]}},
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    assert hermes_main._run_update_pre_gateway_restart_gates(tmp_path) is True
    assert calls == [([str(script)], {"cwd": tmp_path})]
    assert "Running pre-gateway-restart update gate" in capsys.readouterr().out


def test_pre_gateway_restart_gate_failure_aborts_update_before_restart(monkeypatch, tmp_path, capsys):
    script = tmp_path / "scripts" / "check_telegram_quote_gate.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\nexit 2\n")

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"updates": {"pre_gateway_restart_gates": ["scripts/check_telegram_quote_gate.sh"]}},
    )

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="")

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        hermes_main._run_update_pre_gateway_restart_gates(tmp_path)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "failed" in out.lower()
    assert "gateway restart skipped" in out.lower()



def test_update_runs_gate_before_gateway_restart_discovery(monkeypatch):
    """Integration guard: update must run configured gates before restart logic."""
    record = []

    def fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if "list-units" in joined and "hermes-gateway" in joined:
            record.append("restart-discovery")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "rev-parse" in joined and "--abbrev-ref" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
        if "rev-list" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")
        if "rev-parse" in joined and "HEAD" in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_gate(_project_root):
        record.append("gate")
        return True

    monkeypatch.setattr(hermes_main.subprocess, "run", fake_run)
    monkeypatch.setattr(hermes_main.shutil, "which", lambda name: None)
    monkeypatch.setattr(hermes_main, "_run_update_pre_gateway_restart_gates", fake_gate)
    monkeypatch.setattr(hermes_main, "_validate_critical_files_syntax", lambda _root: (True, None, None))
    monkeypatch.setattr(hermes_main, "_install_python_dependencies_with_optional_fallback", lambda *_a, **_k: None)
    monkeypatch.setattr(hermes_main, "_refresh_active_lazy_features", lambda: None)
    monkeypatch.setattr(hermes_main, "_update_node_dependencies", lambda: None)
    monkeypatch.setattr(hermes_main, "_build_web_ui", lambda *_a, **_k: None)
    monkeypatch.setattr(hermes_main, "_print_curator_first_run_notice", lambda: None)
    monkeypatch.setattr(hermes_main, "_print_curator_recent_run_notice", lambda: None)
    monkeypatch.setattr(hermes_main, "_ensure_fhs_path_guard", lambda: None)
    monkeypatch.setattr(hermes_main, "_kill_stale_dashboard_processes", lambda: None)

    with (
        patch("hermes_cli.config.get_missing_env_vars", return_value=[]),
        patch("hermes_cli.config.get_missing_config_fields", return_value=[]),
        patch("hermes_cli.config.check_config_version", return_value=(1, 1)),
        patch("hermes_cli.config.load_config", return_value={"agent": {}}),
        patch("hermes_cli.gateway.supports_systemd_services", return_value=True),
        patch("hermes_cli.gateway._ensure_user_systemd_env", return_value=None),
        patch("hermes_cli.gateway.find_gateway_pids", return_value=[]),
        patch("hermes_cli.gateway.find_profile_gateway_processes", return_value=[]),
        patch("hermes_cli.gateway._get_service_pids", return_value=[]),
    ):
        hermes_main.cmd_update(SimpleNamespace())

    assert record == ["gate", "restart-discovery", "restart-discovery"]
