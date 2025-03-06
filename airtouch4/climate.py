"""AirTouch 4 component to control of AirTouch 4 Climate Devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_DIFFUSE,
    FAN_FOCUS,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AirTouch4ConfigEntry
from .const import DOMAIN

from airtouch4pyapi.airtouch import AirTouchGroup, AirTouchAc

AT_TO_HA_STATE = {
    "Heat": HVACMode.HEAT,
    "Cool": HVACMode.COOL,
    "AutoHeat": HVACMode.AUTO,  # airtouch reports either autoheat or autocool
    "AutoCool": HVACMode.AUTO,
    "Auto": HVACMode.AUTO,
    "Dry": HVACMode.DRY,
    "Fan": HVACMode.FAN_ONLY,
}

HA_STATE_TO_AT = {
    HVACMode.HEAT: "Heat",
    HVACMode.COOL: "Cool",
    HVACMode.AUTO: "Auto",
    HVACMode.DRY: "Dry",
    HVACMode.FAN_ONLY: "Fan",
    HVACMode.OFF: "Off",
}

AT_TO_HA_FAN_SPEED = {
    "Quiet": FAN_DIFFUSE,
    "Low": FAN_LOW,
    "Medium": FAN_MEDIUM,
    "High": FAN_HIGH,
    "Powerful": FAN_FOCUS,
    "Auto": FAN_AUTO,
    "Turbo": "turbo",
}

AT_GROUP_MODES = [HVACMode.OFF, HVACMode.FAN_ONLY]

HA_FAN_SPEED_TO_AT = {value: key for key, value in AT_TO_HA_FAN_SPEED.items()}

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AirTouch4ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the AirTouch 4 Climate entities."""
    coordinator = config_entry.runtime_data
    info = coordinator.data

    # Only add groups that have `TemperatureControl` (ITC Zones)
    climate_entities = [
        AirtouchGroup(coordinator, group["group_number"], info)
        for group in info["groups"]
        if coordinator.airtouch.GetGroupByGroupNumber(
            group["group_number"]
        ).ControlMethod
        == "TemperatureControl"
    ]

    # Only add AC units (Climate devices)
    climate_entities.extend(
        AirtouchAC(coordinator, ac["ac_number"], info) for ac in info["acs"]
    )

    _LOGGER.debug(" Found climate entities %s", climate_entities)

    async_add_entities(climate_entities)


class AirtouchAC(CoordinatorEntity, ClimateEntity):
    """Representation of an AirTouch 4 ac."""

    _attr_has_entity_name = True
    _attr_name = None

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, ac_number, info):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._ac_number = ac_number
        self._airtouch = coordinator.airtouch
        self._info = info
        self._unit = self._airtouch.GetAcs()[ac_number]
        self._attr_unique_id = f"ac_{ac_number}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"ac_{ac_number}")},
            name=f"AC {ac_number}",
            manufacturer="Airtouch",
            model="Airtouch 4",
        )

    @callback
    def _handle_coordinator_update(self):
        """Update internal state from coordinator data."""

        _LOGGER.debug(
            "_handle_coordinator_update: Current AC unit is %s (%s)",
            self._unit,
            type(self._unit),
        )

        # Ensure this is an AC update
        if not isinstance(self._unit, AirTouchAc):
            _LOGGER.error(
                "❌ _handle_coordinator_update: Expected AC but got %s",
                type(self._unit),
            )
            return  # Prevent crash

        # Fetch updated AC list
        acs_data = self._airtouch.GetAcs()

        if not isinstance(acs_data, list):
            _LOGGER.error(
                "❌ _handle_coordinator_update: `GetAcs()` did not return a list! Got: %s",
                type(acs_data),
            )
            return  # Prevent crash

        if self._ac_number >= len(acs_data):
            _LOGGER.error(
                "❌ _handle_coordinator_update: AC index %s is out of range! Total ACs: %s",
                self._ac_number,
                len(acs_data),
            )
            return  # Prevent crash

        updated_unit = acs_data[self._ac_number]  # ✅ Use index instead of `get()`

        if updated_unit is None:
            _LOGGER.error(
                "❌ _handle_coordinator_update: No updated AC data found for AC %s",
                self._ac_number,
            )
            return  # Prevent crash

        self._unit = updated_unit
        _LOGGER.debug(
            "_handle_coordinator_update: ✅ Updated AC unit to %s (%s)",
            self._unit,
            type(self._unit),
        )

        super()._handle_coordinator_update()

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return getattr(self._unit, "Temperature", None)

    @property
    def fan_mode(self):
        """Return fan mode of the AC this group belongs to."""
        ac_unit = self._airtouch.acs[self._ac_number]
        return AT_TO_HA_FAN_SPEED.get(getattr(ac_unit, "AcFanSpeed", "Auto"), FAN_AUTO)

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        airtouch_fan_speeds = self._airtouch.GetSupportedFanSpeedsForAc(self._ac_number)
        return [AT_TO_HA_FAN_SPEED[speed] for speed in airtouch_fan_speeds]

    @property
    def hvac_mode(self):
        """Return HVAC mode, differentiating between ACs and ITC zones."""

        if isinstance(self._unit, AirTouchAc):  # ✅ AC UNIT LOGIC
            is_off = getattr(self._unit, "PowerState", "Off") == "Off"
            return (
                HVACMode.OFF
                if is_off
                else AT_TO_HA_STATE.get(self._unit.AcMode, HVACMode.OFF)
            )

        if isinstance(self._unit, AirTouchGroup):  # ✅ ITC ZONE LOGIC
            if self._unit.ControlMethod == "TemperatureControl":
                return (
                    HVACMode.FAN_ONLY if self._unit.PowerState == "On" else HVACMode.OFF
                )

        _LOGGER.error("hvac_mode called on unexpected unit type: %s", type(self._unit))
        return HVACMode.OFF  # Fallback

    @property
    def hvac_modes(self):
        """Return available HVAC modes, distinguishing ACs and ITC zones."""

        # AC UNIT: Supports full HVAC modes
        if isinstance(self._unit, AirTouchAc):
            return [
                HVACMode.OFF,
                HVACMode.HEAT,
                HVACMode.COOL,
                HVACMode.AUTO,
                HVACMode.DRY,
                HVACMode.FAN_ONLY,
            ]

        # ITC ZONE: Only supports OFF and FAN_ONLY
        if (
            isinstance(self._unit, AirTouchGroup)
            and self._unit.ControlMethod == "TemperatureControl"
        ):
            return [HVACMode.OFF, HVACMode.FAN_ONLY]

        _LOGGER.error("hvac_modes: Unexpected unit type for %s", self._unit)
        return []  # Prevent crashes by returning empty list

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode, differentiating between AC (full modes) and ITC zones (limited)."""

        if isinstance(self._unit, AirTouchAc):
            # ✅ This is a full AC unit → allow all modes from HA_STATE_TO_AT
            if hvac_mode == HVACMode.OFF:
                await self.async_turn_off()
                return
            if hvac_mode not in HA_STATE_TO_AT:
                raise ValueError(f"Unsupported HVAC mode for AC: {hvac_mode}")

            # Set the new mode
            _LOGGER.debug("Setting AC %s to %s", self._ac_number, hvac_mode)
            await self._airtouch.SetCoolingModeForAc(
                self._ac_number, HA_STATE_TO_AT[hvac_mode]
            )
            # Also ensure AC is ON
            await self.async_turn_on()
            self._unit = self._airtouch.GetAcs()[self._ac_number]
            self.async_write_ha_state()
            return

        if isinstance(self._unit, AirTouchGroup):
            # ✅ ITC zone → only allow OFF and FAN_ONLY
            if hvac_mode not in [HVACMode.OFF, HVACMode.FAN_ONLY]:
                raise ValueError(f"Unsupported HVAC mode for ITC zone: {hvac_mode}")

            _LOGGER.debug("Setting ITC zone %s to %s", self._group_number, hvac_mode)
            if hvac_mode == HVACMode.OFF:
                await self.async_turn_off()
            else:
                await self.async_turn_on()
            self.async_write_ha_state()
            return

        # Fallback
        _LOGGER.error(
            "async_set_hvac_mode called on unexpected unit type: %s", type(self._unit)
        )
        raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        if fan_mode not in self.fan_modes:
            raise ValueError(f"Unsupported fan mode: {fan_mode}")

        _LOGGER.debug("Setting fan mode of %s to %s", self._ac_number, fan_mode)
        await self._airtouch.SetFanSpeedForAc(
            self._ac_number, HA_FAN_SPEED_TO_AT[fan_mode]
        )
        self._unit = self._airtouch.GetAcs()[self._ac_number]
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on either AC or ITC zone, depending on the entity type."""
        if isinstance(self._unit, AirTouchAc):
            # ✅ AC logic
            _LOGGER.debug(
                "Turning ON AC: %s (ac_number=%s)", self.unique_id, self._ac_number
            )
            await self._airtouch.TurnAcOn(self._ac_number)
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
        elif (
            isinstance(self._unit, AirTouchGroup)
            and self._unit.ControlMethod == "TemperatureControl"
        ):
            # ✅ ITC zone logic
            _LOGGER.debug(
                "Turning ON ITC zone: %s (group_number=%s)",
                self.unique_id,
                self._group_number,
            )
            await self._airtouch.TurnGroupOn(self._group_number)
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
        else:
            _LOGGER.error(
                "async_turn_on called on unexpected unit type: %s", type(self._unit)
            )

    async def async_turn_off(self) -> None:
        """Turn off either AC or ITC zone, depending on the entity type."""
        if isinstance(self._unit, AirTouchAc):
            # ✅ AC logic
            _LOGGER.debug(
                "Turning OFF AC: %s (ac_number=%s)", self.unique_id, self._ac_number
            )
            await self._airtouch.TurnAcOff(self._ac_number)
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
        elif (
            isinstance(self._unit, AirTouchGroup)
            and self._unit.ControlMethod == "TemperatureControl"
        ):
            # ✅ ITC zone logic
            _LOGGER.debug(
                "Turning OFF ITC zone: %s (group_number=%s)",
                self.unique_id,
                self._group_number,
            )
            await self._airtouch.TurnGroupOff(self._group_number)
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
        else:
            _LOGGER.error(
                "async_turn_off called on unexpected unit type: %s", type(self._unit)
            )


class AirtouchGroup(CoordinatorEntity, ClimateEntity):
    """Representation of an AirTouch 4 group."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = AT_GROUP_MODES
    _enable_turn_on_off_backwards_compatibility = False
    """ added above line """

    def __init__(self, coordinator, group_number, info):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._group_number = group_number
        self._attr_unique_id = group_number
        self._airtouch = coordinator.airtouch
        self._info = info
        self._unit = self._airtouch.GetGroupByGroupNumber(group_number)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, group_number)},
            manufacturer="Airtouch",
            model="Airtouch 4",
            name=self._unit.GroupName,
        )

    @callback
    def _handle_coordinator_update(self):
        """Update internal state from coordinator data."""

        _LOGGER.debug(
            "_handle_coordinator_update: Current Group is %s (%s)",
            self._unit,
            type(self._unit),
        )

        # Ensure we only process Group updates in this class
        if not isinstance(self._unit, AirTouchGroup):
            _LOGGER.error(
                "❌ _handle_coordinator_update: Expected Group but got %s",
                type(self._unit),
            )
            return  # Prevent crash

        # Fetch updated Group data
        updated_unit = self._airtouch.GetGroupByGroupNumber(self._group_number)

        if updated_unit is None:
            _LOGGER.error(
                "❌ _handle_coordinator_update: No updated Group data found for Group %s",
                self._group_number,
            )
            return  # Prevent crash

        self._unit = updated_unit
        _LOGGER.debug(
            "_handle_coordinator_update: ✅ Updated Group to %s (%s)",
            self._unit,
            type(self._unit),
        )

        super()._handle_coordinator_update()

    @property
    def min_temp(self):
        """Return Minimum Temperature for AC of this group."""
        return self._airtouch.acs[self._unit.BelongsToAc].MinSetpoint

    @property
    def max_temp(self):
        """Return Max Temperature for AC of this group."""
        return self._airtouch.acs[self._unit.BelongsToAc].MaxSetpoint

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._unit.Temperature

    @property
    def target_temperature(self):
        """Return the temperature we are trying to reach."""
        return self._unit.TargetSetpoint

    @property
    def hvac_mode(self):
        """Return hvac target hvac state for a group."""
        if not hasattr(self._unit, "PowerState"):  # Ensure this isn't an AC
            _LOGGER.error(
                "hvac_mode called on Group instead of AC: %s", self._unit.GroupName
            )
            return None  # Prevent crashes

        is_off = self._unit.PowerState == "Off"
        return (
            HVACMode.OFF if is_off else HVACMode.FAN_ONLY
        )  # Groups should not have full HVAC modes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        if hvac_mode not in HA_STATE_TO_AT:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        if self.hvac_mode == HVACMode.OFF:
            await self.async_turn_on()
        self._unit = self._airtouch.GetGroups()[self._group_number]
        _LOGGER.debug(
            "Setting operation mode of %s to %s", self._group_number, hvac_mode
        )
        self.async_write_ha_state()

    @property
    def fan_mode(self):
        """Return fan mode of the AC this group belongs to."""
        return AT_TO_HA_FAN_SPEED[self._airtouch.acs[self._unit.BelongsToAc].AcFanSpeed]

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        airtouch_fan_speeds = self._airtouch.GetSupportedFanSpeedsByGroup(
            self._group_number
        )
        return [AT_TO_HA_FAN_SPEED[speed] for speed in airtouch_fan_speeds]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperatures."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            _LOGGER.debug("Argument `temperature` is missing in set_temperature")
            return

        _LOGGER.debug("Setting temp of %s to %s", self._group_number, str(temp))
        self._unit = await self._airtouch.SetGroupToTemperature(
            self._group_number, int(temp)
        )
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        if fan_mode not in self.fan_modes:
            raise ValueError(f"Unsupported fan mode: {fan_mode}")

        _LOGGER.debug("Setting fan mode of %s to %s", self._group_number, fan_mode)
        self._unit = await self._airtouch.SetFanSpeedByGroup(
            self._group_number, HA_FAN_SPEED_TO_AT[fan_mode]
        )
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on."""
        _LOGGER.debug("Turning %s on", self.unique_id)
        await self._airtouch.TurnGroupOn(self._group_number)

        # in case ac is not on. Airtouch turns itself off if no groups are turned on
        # (even if groups turned back on)
        await self._airtouch.TurnAcOn(
            self._airtouch.GetGroupByGroupNumber(self._group_number).BelongsToAc
        )
        # this might cause the ac object to be wrong, so force the shared data
        # store to update
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off."""
        _LOGGER.debug("Turning %s off", self.unique_id)
        await self._airtouch.TurnGroupOff(self._group_number)
        # this will cause the ac object to be wrong
        # (ac turns off automatically if no groups are running)
        # so force the shared data store to update
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
