"""ThermoTouch climate entity."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import DOMAIN, MODES
from .entity import ThermoTouchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ThermoTouchClimate(coordinator, entry)])


class ThermoTouchClimate(ThermoTouchEntity, ClimateEntity):
    _attr_name = None                      # the device name is the entity name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_preset_modes = MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("climate")

    @property
    def current_temperature(self):
        return self._state.get("room_c")

    @property
    def target_temperature(self):
        return self._state.get("setpoint_c")

    @property
    def preset_mode(self):
        return self._state.get("mode")

    @property
    def hvac_action(self):
        heating = self._state.get("heating")
        if heating is None:
            return None
        return HVACAction.HEATING if heating else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.async_set(setpoint=float(temp))

    async def async_set_preset_mode(self, preset_mode):
        await self.coordinator.async_set(mode=preset_mode)
