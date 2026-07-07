"""Airwallex addon routes — thin delegates to shared payment route factory."""

from __future__ import annotations

from typing import Any

from app.addons.payments.shared_routes import build_payment_routers


def _parse_airwallex_config_form(form: Any) -> tuple[dict[str, Any], bool]:
    return (
        {
            "client_id": form.get("client_id", ""),
            "api_key": form.get("api_key", ""),
            "webhook_secret": form.get("webhook_secret", ""),
            "return_url": form.get("return_url", ""),
        },
        form.get("is_enabled") == "on",
    )


admin_router, api_router, jinja_env = build_payment_routers(
    "airwallex",
    template_name="airwallex_config.html",
    page_title="Airwallex Settings",
    secret_keys=("client_id", "api_key", "webhook_secret"),
    parse_config_form=_parse_airwallex_config_form,
)
