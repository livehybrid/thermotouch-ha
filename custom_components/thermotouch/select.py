"""Towel rail select."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .const import DOMAIN, RAIL_OPTIONS
from .entity import ThermoTouchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ThermoTouchRail(coordinator, entry)])


class ThermoTouchRail(ThermoTouchEntity, SelectEntity):
    _attr_name = "Towel rail"
    _attr_icon = "mdi:radiator"
    _attr_options = RAIL_OPTIONS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("rail")

    @property
    def current_option(self):
        return self._state.get("rail")

    async def async_select_option(self, option):
        await self.coordinator.async_set(rail=option)
