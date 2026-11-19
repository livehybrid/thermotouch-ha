"""Binary sensors: heating and towel-rail running."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .entity import ThermoTouchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ThermoTouchHeating(coordinator, entry),
        ThermoTouchRailRunning(coordinator, entry),
    ])


class ThermoTouchHeating(ThermoTouchEntity, BinarySensorEntity):
    _attr_name = "Heating"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("heating")

    @property
    def is_on(self):
        return self._state.get("heating")


class ThermoTouchRailRunning(ThermoTouchEntity, BinarySensorEntity):
    _attr_name = "Towel rail running"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("rail_running")

    @property
    def is_on(self):
        return self._state.get("rail_running")
