"""Regression: `/model` must be SESSION-SCOPED by default (Nicha policy).

Guards against a Hermes update silently reverting the built-in default of
``resolve_persist_behavior`` to ``True`` (upstream behavior), which would make
every ad-hoc ``/model`` switch clobber the global default again.
"""
from unittest.mock import patch

from hermes_cli.model_switch import resolve_persist_behavior


def test_bare_switch_session_scoped_when_config_missing_key():
    # Config lost the key (e.g. post-update migration reset) -> still session-only.
    with patch("hermes_cli.config.load_config",
               return_value={"model": {"default": "x", "provider": "y"}}):
        assert resolve_persist_behavior(False, False) is False


def test_bare_switch_session_scoped_when_model_flat_string():
    # Fresh install: model may be a flat string, not a dict.
    with patch("hermes_cli.config.load_config", return_value={"model": ""}):
        assert resolve_persist_behavior(False, False) is False


def test_explicit_global_still_persists():
    assert resolve_persist_behavior(True, False) is True


def test_explicit_session_opts_out():
    assert resolve_persist_behavior(False, True) is False


def test_explicit_config_true_is_honored():
    # If someone deliberately sets it true, honor it (opt-in to global).
    with patch("hermes_cli.config.load_config",
               return_value={"model": {"persist_switch_by_default": True}}):
        assert resolve_persist_behavior(False, False) is True
