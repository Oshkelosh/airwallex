# Airwallex (`airwallex`)

Accept payments via Airwallex.

## Overview

| | |
|---|---|
| Addon ID | `airwallex` |
| Category | payment |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Only **one** payment addon can be active at a time.

## Enable and configure

1. Install this package under `app/addons/payments/airwallex/`
2. Open **Admin → Payments → Airwallex** at `/admin/payments/airwallex`
3. Enter credentials and enable **Enable this payment processor**

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `client_id` | secret | Airwallex client ID |
| `api_key` | secret | Airwallex API key |
| `webhook_secret` | secret | Webhook signing secret |
| `return_url` | string | Redirect after payment |

Secrets are stored in `addon_configs`, not in `.env`.

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/payments/airwallex/checkout` | Start checkout (optional; prefer generic order checkout) |
| POST | `/api/v1/payments/airwallex/webhook` | PSP webhook endpoint |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/payments/airwallex` | Config form |
| POST | `/admin/payments/airwallex/save` | Save config |

## Core integration

- **Storefront checkout:** `POST /api/v1/orders/{order_id}/checkout` → `PaymentAddon.create_payment()` → redirect URL
- **Webhook:** `POST /api/v1/payments/airwallex/webhook` → `parse_webhook()` → core `process_payment_webhook()`
- **Amounts:** smallest currency unit (cents)

## Provider setup

Register webhook URL (replace `{PUBLIC_APP_URL}` with your public base URL):

```
{PUBLIC_APP_URL}/api/v1/payments/airwallex/webhook
```

Webhook signature header: **`signature (default)`**

1. Obtain demo API credentials from the Airwallex sandbox.
2. Register webhook URL in the Airwallex developer portal.

## Known limitations

API base URL is currently hardcoded to the Airwallex demo environment; no live/production URL toggle in config.

## Package layout

```
airwallex/
├── README.md
├── addon.py
├── routes.py
└── templates/
```

## See also

- [Payment addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
