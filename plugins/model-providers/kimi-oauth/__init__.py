"""Kimi OAuth provider profile — reads Kimi Code CLI credentials.

Tokens are managed by Kimi Code CLI (OAuth device code flow) and stored in
~/.kimi-code/credentials/kimi-code.json (new CLI) or
~/.kimi/credentials/kimi-code.json (legacy). This provider exposes them to
Hermes as an ``oauth_external`` provider — no API key needed in config/.env.
"""

from providers import register_provider
from providers.base import ProviderProfile


class KimiOAuthProfile(ProviderProfile):
    """Kimi Code OAuth — Anthropic Messages API via Kimi Code CLI tokens."""

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context
    ) -> tuple[dict, dict]:
        """Kimi OAuth uses the Anthropic Messages API path."""
        extra_body = {}
        top_level = {}
        if reasoning_config and isinstance(reasoning_config, dict):
            enabled = reasoning_config.get("enabled", True)
            if enabled is False:
                extra_body["thinking"] = {"type": "disabled"}
            else:
                extra_body["thinking"] = {"type": "enabled"}
                effort = (reasoning_config.get("effort") or "").strip().lower()
                if effort in {"low", "medium", "high"}:
                    top_level["reasoning_effort"] = effort
                else:
                    top_level["reasoning_effort"] = "medium"
        else:
            extra_body["thinking"] = {"type": "enabled"}
            top_level["reasoning_effort"] = "medium"
        return extra_body, top_level


kimi_oauth = KimiOAuthProfile(
    name="kimi-oauth",
    aliases=("kimi-code", "kimi-code-oauth", "kimi_oauth"),
    display_name="Kimi Code (OAuth)",
    description="Kimi Code OAuth — reuses Kimi Code CLI login (kimi login)",
    signup_url="https://code.kimi.com/kimi-code",
    api_mode="anthropic_messages",
    env_vars=(),  # OAuth — tokens in Kimi Code CLI credential store, not env
    base_url="https://api.kimi.com/coding/v1",
    auth_type="oauth_external",
    default_aux_model="kimi-k2.6",
    default_max_tokens=65536,
)

register_provider(kimi_oauth)
