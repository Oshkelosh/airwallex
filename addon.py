"""
Airwallex payment integration.

Supports payment intents, refunds, and webhooks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import (
    create_payment_error,
    effective_redirect_url,
    extract_order_id,
    header_get,
    mock_checkout,
    verify_hmac_sha256_hex,
)
from schemas.payment import PaymentWebhookOutcome
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config

_API_BASE = "https://api-demo.airwallex.com/api/v1"


class AirwallexConfig(BaseModel):
    client_id: SecretStr = Field(default=..., description="Airwallex client ID")
    api_key: SecretStr = Field(default=..., description="Airwallex API key")
    webhook_secret: SecretStr = Field(default=..., description="Webhook signing secret")
    return_url: str = Field(
        default="",
        description="Optional override for return redirect (leave blank to use Site URL)",
    )

    @classmethod
    def config_model(cls):
        return cls


class AirwallexAddon(PaymentAddon):
    addon_id: str = "airwallex"
    addon_name: str = "Airwallex"
    addon_description: str = "Accept payments via Airwallex."
    addon_category: str = "payment"
    version: str = "1.0.0"
    is_enabled: bool = False

    _config: Dict[str, Any] | None = None
    _client_id: str | None = None
    _api_key: str | None = None
    _webhook_secret: str | None = None
    _return_url: str = ""
    _access_token: str | None = None

    @classmethod
    def config_schema(cls):
        return AirwallexConfig

    async def initialize(self, config: dict) -> None:
        validated = self.config_schema()(**config)
        self._config = dump_addon_config(validated)
        self._client_id = validated.client_id.get_secret_value()
        self._api_key = validated.api_key.get_secret_value()
        self._webhook_secret = validated.webhook_secret.get_secret_value()
        self._return_url = validated.return_url
        self._access_token = None
        self.is_enabled = True
        info("Airwallex", "Initialized")

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        client_id = validated.client_id.get_secret_value()
        api_key = validated.api_key.get_secret_value()
        if not client_id or not api_key:
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_API_BASE}/authentication/login",
                headers={
                    "x-client-id": client_id,
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={},
            )
        if resp.status_code == 401:
            raise ValidationError(message="Invalid API credentials — check your credentials")
        if resp.status_code == 403:
            raise ValidationError(
                message="Credentials are valid but missing required permissions: authentication"
            )
        if resp.status_code >= 400:
            raise ValidationError(message="Airwallex rejected the API credentials")

    async def shutdown(self) -> None:
        self._client_id = None
        self._api_key = None
        self._webhook_secret = None
        self._access_token = None
        self.is_enabled = False

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        if not self._client_id or not self._api_key:
            raise RuntimeError("Airwallex credentials not configured")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_API_BASE}/authentication/login",
                headers={
                    "x-client-id": self._client_id,
                    "x-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={},
            )
            resp.raise_for_status()
            self._access_token = resp.json()["token"]
            return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method,
                f"{_API_BASE}{path}",
                headers=headers,
                json=json_body,
            )
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}

    async def create_payment(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        *,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Dict[str, Any]:
        if not self._client_id:
            return mock_checkout("airwallex", order_id, amount, currency)

        effective_return = effective_redirect_url(
            self._return_url, fallback=return_url or ""
        )

        body: dict[str, Any] = {
            "request_id": f"order_{order_id}",
            "amount": amount / 100,
            "currency": currency.upper(),
            "merchant_order_id": order_id,
            "metadata": {"order_id": order_id},
            "return_url": effective_return,
        }
        if customer_email:
            body["customer"] = {"email": customer_email}

        try:
            data = await self._request("POST", "/pa/payment_intents/create", json_body=body)
            return {
                "success": True,
                "payment_id": data.get("id", ""),
                "session_id": data.get("id", ""),
                "url": data.get("next_action", {}).get("url", effective_return),
                "order_id": order_id,
            }
        except Exception as exc:
            warning("Airwallex", "create_payment error: {}", exc)
            return create_payment_error("airwallex", exc, order_id)

    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        if not self._client_id:
            return {"success": False, "error": "Airwallex credentials not configured"}

        try:
            data = await self._request(
                "POST",
                f"/pa/payment_intents/{payment_id}/confirm",
            )
            return {
                "success": True,
                "payment_id": payment_id,
                "status": data.get("status", "confirmed"),
                "amount": int(float(data.get("amount", 0)) * 100),
            }
        except Exception as exc:
            warning("Airwallex", "confirm_payment({}) error: {}", payment_id, exc)
            return {"success": False, "error": str(exc)}

    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        if not self._client_id:
            return {"success": False, "error": "Airwallex credentials not configured"}

        body = {"amount": amount / 100, "payment_intent_id": payment_id}
        try:
            data = await self._request("POST", "/pa/refunds/create", json_body=body)
            return {
                "success": True,
                "refund_id": data.get("id", ""),
                "amount": amount,
                "status": data.get("status", "succeeded"),
            }
        except Exception as exc:
            warning("Airwallex", "refund_payment({}) error: {}", payment_id, exc)
            return {"success": False, "error": str(exc)}

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not self._client_id:
            return {"payment_id": payment_id, "status": "error", "detail": "Not configured"}

        try:
            data = await self._request("GET", f"/pa/payment_intents/{payment_id}")
            return {
                "payment_id": payment_id,
                "status": data.get("status", "unknown"),
                "amount": int(float(data.get("amount", 0)) * 100),
                "currency": data.get("currency", "usd").lower(),
            }
        except Exception as exc:
            warning("Airwallex", "get_payment_status({}) error: {}", payment_id, exc)
            return {"payment_id": payment_id, "status": "error", "detail": str(exc)}

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Verify Airwallex x-signature (HMAC-SHA256 hex of x-timestamp + body)."""
        if not self._webhook_secret:
            warning("Airwallex", "verify_webhook skipped: webhook secret not configured")
            return False
        signature = header_get(headers, "x-signature")
        timestamp = header_get(headers, "x-timestamp")
        if not timestamp:
            return False
        return verify_hmac_sha256_hex(
            self._webhook_secret,
            body,
            signature,
            prefix=timestamp.encode("utf-8"),
        )

    async def parse_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> PaymentWebhookOutcome:
        try:
            event_type = payload.get("name", payload.get("type", ""))
            event_data = payload.get("data", payload)
            event_id = str(payload.get("id", ""))
            info("Airwallex", "Webhook received: {}", event_type)

            if event_type in ("payment_intent.succeeded", "payment_intent.capture_succeeded"):
                order_id = extract_order_id(event_data.get("metadata"))
                return PaymentWebhookOutcome(
                    handled=True,
                    event_id=event_id,
                    event_type=event_type,
                    mark_paid=order_id is not None,
                    order_id=order_id,
                    payment_id=str(event_data.get("id", "")) or None,
                )

            return PaymentWebhookOutcome(
                handled=True,
                event_id=event_id,
                event_type=event_type,
            )
        except Exception as exc:
            warning("Airwallex", "parse_webhook error: {}", exc)
            return PaymentWebhookOutcome(handled=False, error=str(exc))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.payments.airwallex.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.payments.airwallex.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
