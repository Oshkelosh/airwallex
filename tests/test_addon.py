"""Minimal unit tests for the airwallex addon."""

from app.addons.payments.airwallex.addon import AirwallexAddon


def test_addon_identity():
    assert AirwallexAddon.addon_id == "airwallex"
    assert AirwallexAddon.addon_category == "payment"
