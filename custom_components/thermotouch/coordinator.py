"""Polling coordinator for a ThermoTouch thermostat."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import SlotBusy, ThermoTouchClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ThermoTouchCoordinator(DataUpdateCoordinator):
    """Reads device state on an interval; keeps the last good state when the vendor app
    is holding the single session slot (a read then returns no state)."""

    def __init__(self, hass, client: ThermoTouchClient, mac, scan_interval=DEFAULT_SCAN_INTERVAL):
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} {mac}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.mac = mac
        self.data = {}

    async def _async_update_data(self):
        try:
            state = await self.hass.async_add_executor_job(self.client.poll)
        except SlotBusy:
            # vendor app likely connected; keep the last known state rather than erroring
            _LOGGER.debug("%s: read skipped (session busy)", self.mac)
            return self.data or {}
        except Exception as err:  # noqa: BLE001 - surface as an update failure
            _LOGGER.debug("%s: poll failed: %s", self.mac, err)
            return self.data or {}
        return state

    async def async_set(self, **kw):
        """Send a command, then refresh. Surfaces a busy slot as a clear error."""
        from homeassistant.exceptions import HomeAssistantError

        try:
            await self.hass.async_add_executor_job(lambda: self.client.set(**kw))
        except SlotBusy as err:
            raise HomeAssistantError(
                "ThermoTouch is busy (the vendor app is open); command not applied"
            ) from err
        await self.async_request_refresh()
