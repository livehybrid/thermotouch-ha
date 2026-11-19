"""Config flow for ThermoTouch."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME

from .client import SlotBusy, ThermoTouchClient, ThermoTouchError
from .const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TEMPLATE,
    CONF_TOKEN,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _norm_mac(mac: str) -> str:
    h = mac.replace(":", "").replace("-", "").replace(" ", "").upper()
    if len(h) != 12 or not all(c in "0123456789ABCDEF" for c in h):
        raise ValueError("mac")
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


class ThermoTouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                mac = _norm_mac(user_input[CONF_MAC])
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                try:
                    client = ThermoTouchClient(
                        mac=mac,
                        token=user_input[CONF_TOKEN],
                        command_template=user_input.get(CONF_TEMPLATE) or None,
                        host=user_input.get(CONF_HOST, DEFAULT_HOST),
                        port=user_input.get(CONF_PORT, DEFAULT_PORT),
                    )
                except ThermoTouchError:
                    errors[CONF_TOKEN] = "invalid_token"
                else:
                    ok = await self._validate(client)
                    if ok is False:
                        errors["base"] = "cannot_connect"
                    else:
                        data = {
                            CONF_MAC: mac,
                            CONF_TOKEN: user_input[CONF_TOKEN],
                            CONF_TEMPLATE: user_input.get(CONF_TEMPLATE) or None,
                            CONF_HOST: user_input.get(CONF_HOST, DEFAULT_HOST),
                            CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        }
                        return self.async_create_entry(
                            title=user_input.get(CONF_NAME) or f"ThermoTouch {mac[-5:]}",
                            data=data,
                        )

        schema = vol.Schema({
            vol.Required(CONF_NAME, default="ThermoTouch UFH"): str,
            vol.Required(CONF_MAC): str,
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_TEMPLATE): str,
            vol.Optional(CONF_HOST, default=DEFAULT_HOST): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _validate(self, client):
        """True if a read succeeded, None if the slot is busy (still valid), False otherwise."""
        try:
            await self.hass.async_add_executor_job(client.poll)
            return True
        except SlotBusy:
            return None            # token accepted elsewhere; the vendor app is just connected
        except Exception:          # noqa: BLE001
            return False
