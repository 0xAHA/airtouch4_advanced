"""AirTouch4 component to control AirTouch4 Climate Devices."""
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_DEFAULT, MODE_NONITC_FAN, MODE_NONITC_CLIMATE, MIN_FAN_SPEED, MAX_FAN_SPEED, AUTO_MAX_TEMP, AUTO_MIN_TEMP
from .coordinator import AirtouchDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Mappings between AirTouch and HA HVAC modes
AT_TO_HA_STATE = {
    "Heat": HVACMode.HEAT,
    "Cool": HVACMode.COOL,
    "AutoHeat": HVACMode.AUTO,
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
HA_FAN_SPEED_TO_AT = {value: key for key, value in AT_TO_HA_FAN_SPEED.items()}

# For ITC zones, we use only OFF and FAN_ONLY.
AT_GROUP_MODES = [HVACMode.OFF, HVACMode.FAN_ONLY]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up AirTouch4 climate entities from a config entry.
    
    - AC units are always created as AirtouchAC.
    - ITC zones (TemperatureControl) are always created as AirtouchGroup.
    - For non-ITC zones (PercentageControl):
         * If setup_mode == MODE_NONITC_FAN, skip them here (they will be created as fans).
         * If setup_mode == MODE_NONITC_CLIMATE, create ManualNonITCClimate.
         * Otherwise (default), treat them as standard AirtouchGroup.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AirtouchDataUpdateCoordinator = data["coordinator"]

    setup_mode = entry.data.get("setup_mode", MODE_DEFAULT)
    sensor_map = entry.data.get("nonitc_sensors", {})

    info = coordinator.data  # {"acs": [...], "groups": [...]}
    climate_entities = []

    # 1) AC Entities
    for ac_dict in info["acs"]:
        ac_number = ac_dict["ac_number"]
        climate_entities.append(AirtouchAC(coordinator, ac_number))

    # 2) Group Entities
    for group_dict in info["groups"]:
        group_number = group_dict["group_number"]
        group_obj = coordinator.airtouch.GetGroupByGroupNumber(group_number)
        control_method = getattr(group_obj, "ControlMethod", "Unknown")

        if control_method == "TemperatureControl":
            climate_entities.append(AirtouchGroup(coordinator, group_number))
        else:
            if setup_mode == MODE_NONITC_FAN:
                continue
            elif setup_mode == MODE_NONITC_CLIMATE:
                # Look up sensor using the string form of the group number
                sensor_entity_id = sensor_map.get(str(group_number))
                climate_entities.append(ManualNonITCClimate(coordinator, group_number, sensor_entity_id))
            else:
                climate_entities.append(AirtouchGroup(coordinator, group_number))

    _LOGGER.debug("Adding climate entities: %s", climate_entities)

    # Store ManualNonITCClimate entities for periodic fan adjustments.
    hass.data.setdefault(DOMAIN, {}).setdefault("manual_climates", [])
    for entity in climate_entities:
        if isinstance(entity, ManualNonITCClimate):
            hass.data[DOMAIN]["manual_climates"].append(entity)

    async_add_entities(climate_entities)

class AirtouchAC(CoordinatorEntity, ClimateEntity):
    """Representation of an AirTouch4 AC unit as a climate entity."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, ac_number: int):
        super().__init__(coordinator)
        self._ac_number = ac_number
        self._airtouch = coordinator.airtouch
        self._unit = self._airtouch.GetAcs()[ac_number]
        self._attr_unique_id = f"ac_{ac_number}"
        self._attr_name = f"AC {ac_number}"

    @callback
    def _handle_coordinator_update(self):
        self._unit = self._airtouch.GetAcs()[self._ac_number]
        super()._handle_coordinator_update()

    @property
    def current_temperature(self) -> float | None:
        return getattr(self._unit, "Temperature", None)

    @property
    def fan_mode(self) -> str | None:
        raw_speed = getattr(self._unit, "AcFanSpeed", "Auto")
        return AT_TO_HA_FAN_SPEED.get(raw_speed, None)

    @property
    def fan_modes(self) -> list[str]:
        speeds = self._airtouch.GetSupportedFanSpeedsForAc(self._ac_number)
        return [AT_TO_HA_FAN_SPEED.get(s, FAN_AUTO) for s in speeds]

    @property
    def hvac_mode(self) -> HVACMode:
        if getattr(self._unit, "PowerState", "Off") == "Off":
            return HVACMode.OFF
        raw_mode = getattr(self._unit, "AcMode", "Fan")
        return AT_TO_HA_STATE.get(raw_mode, HVACMode.FAN_ONLY)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        raw_modes = self._airtouch.GetSupportedCoolingModesForAc(self._ac_number)
        results = [AT_TO_HA_STATE[m] for m in raw_modes if m in AT_TO_HA_STATE]
        results.append(HVACMode.OFF)
        return results

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in HA_STATE_TO_AT:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        raw_mode = HA_STATE_TO_AT[hvac_mode]
        await self._airtouch.SetCoolingModeForAc(self._ac_number, raw_mode)
        await self._airtouch.TurnAcOn(self._ac_number)
        self._unit = self._airtouch.GetAcs()[self._ac_number]
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in self.fan_modes:
            raise ValueError(f"Unsupported fan mode: {fan_mode}")
        raw_speed = {v: k for k, v in AT_TO_HA_FAN_SPEED.items()}.get(fan_mode, "Auto")
        await self._airtouch.SetFanSpeedForAc(self._ac_number, raw_speed)
        self._unit = self._airtouch.GetAcs()[self._ac_number]
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self._airtouch.TurnAcOn(self._ac_number)

    async def async_turn_off(self) -> None:
        await self._airtouch.TurnAcOff(self._ac_number)
        self.async_write_ha_state()


class AirtouchGroup(CoordinatorEntity, ClimateEntity):
    """Representation of a standard ITC zone as a climate entity."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, group_number: int):
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch
        self._unit = self._airtouch.GetGroupByGroupNumber(group_number)
        self._attr_unique_id = f"group_{group_number}"
        self._attr_name = getattr(self._unit, "GroupName", f"Zone {group_number}")

    @callback
    def _handle_coordinator_update(self):
        self._unit = self._airtouch.GetGroupByGroupNumber(self._group_number)
        super()._handle_coordinator_update()

    @property
    def current_temperature(self) -> float | None:
        return getattr(self._unit, "Temperature", None)

    @property
    def target_temperature(self) -> float | None:
        return getattr(self._unit, "TargetSetpoint", None)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            _LOGGER.debug("No temperature provided for group %s", self._group_number)
            return
        try:
            _LOGGER.debug("Setting group %s temperature to %s", self._group_number, temp)
            self._unit = await self._airtouch.SetGroupToTemperature(self._group_number, int(temp))
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.exception("Error in async_set_temperature for group %s: %s", self._group_number, exc)
            raise exc

    @property
    def hvac_mode(self) -> HVACMode:
        if getattr(self._unit, "PowerState", "Off") == "Off":
            return HVACMode.OFF
        return HVACMode.FAN_ONLY

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            if self.hvac_mode == HVACMode.OFF:
                await self.async_turn_on()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        _LOGGER.debug("Turning group %s ON", self._group_number)
        await self._airtouch.TurnGroupOn(self._group_number)
        belongs_to = getattr(self._unit, "BelongsToAc", 0)
        await self._airtouch.TurnAcOn(belongs_to)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        _LOGGER.debug("Turning group %s OFF", self._group_number)
        await self._airtouch.TurnGroupOff(self._group_number)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def min_temp(self) -> float:
        belongs_to = getattr(self._unit, "BelongsToAc", 0)
        try:
            return getattr(self._airtouch.acs[belongs_to], "MinSetpoint", 16)
        except (IndexError, AttributeError):
            return 16

    @property
    def max_temp(self) -> float:
        belongs_to = getattr(self._unit, "BelongsToAc", 0)
        try:
            return getattr(self._airtouch.acs[belongs_to], "MaxSetpoint", 30)
        except (IndexError, AttributeError):
            return 30


class ManualNonITCClimate(CoordinatorEntity, ClimateEntity):
    """
    A manual (faux) climate entity for non-ITC zones.
    - Uses a user-selected temperature sensor for current_temperature.
    - Stores target_temperature locally (since the API cannot set it).
    - Supports only OFF and FAN_ONLY modes.
    - Exposes the current open percentage as an extra attribute.
    """

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: AirtouchDataUpdateCoordinator,
        group_number: int,
        sensor_entity_id: str | None = None,
    ):
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch
        # sensor_entity_id now is properly read (from sensor_map using str(key))
        self._sensor_entity_id = sensor_entity_id

        group_obj = self._airtouch.GetGroupByGroupNumber(group_number)
        self._attr_name = group_obj.GroupName  # Use the group name as-is
        self._attr_unique_id = f"manual_nonitc_climate_{group_number}"
        self._target_temp = 24.0

    @callback
    def _handle_coordinator_update(self):
        # For manual non-ITC climate, we don't update the target temperature.
        super()._handle_coordinator_update()

    @property
    def hvac_mode(self) -> HVACMode:
        group_obj = self._airtouch.GetGroupByGroupNumber(self._group_number)
        if getattr(group_obj, "PowerState", "Off") == "Off":
            return HVACMode.OFF
        return HVACMode.FAN_ONLY

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return self._attr_hvac_modes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._airtouch.TurnGroupOff(self._group_number)
        else:
            await self._airtouch.TurnGroupOn(self._group_number)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self._airtouch.TurnGroupOn(self._group_number)
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._airtouch.TurnGroupOff(self._group_number)
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        if not self._sensor_entity_id:
            _LOGGER.debug("ManualNonITCClimate: No sensor_entity_id provided for group %s", self._group_number)
            return None
        state_obj = self.hass.states.get(self._sensor_entity_id)
        if not state_obj or state_obj.state in ("unknown", "unavailable"):
            _LOGGER.debug("ManualNonITCClimate: Sensor %s state is %s for group %s", self._sensor_entity_id, state_obj.state if state_obj else None, self._group_number)
            return None
        try:
            temp = float(state_obj.state)
            _LOGGER.debug("ManualNonITCClimate: Sensor %s reports temperature %.2f for group %s", self._sensor_entity_id, temp, self._group_number)
            return temp
        except ValueError:
            _LOGGER.debug("ManualNonITCClimate: Sensor %s value %s cannot be converted for group %s", self._sensor_entity_id, state_obj.state, self._group_number)
            return None

    @property
    def target_temperature(self) -> float:
        return self._target_temp

    async def async_set_temperature(self, **kwargs: Any) -> None:
        new_temp = kwargs.get(ATTR_TEMPERATURE)
        if new_temp is None:
            _LOGGER.debug("No temperature provided for manual non-ITC zone %s", self._group_number)
            return
        self._target_temp = float(new_temp)
        _LOGGER.debug("Manual non-ITC zone %s target temperature set to %s", self._group_number, self._target_temp)
        self.async_write_ha_state()

    @property
    def min_temp(self) -> float:
        return 16.0

    @property
    def max_temp(self) -> float:
        return 30.0

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes including current open percentage from coordinator data."""
        groups = self.coordinator.data.get("groups", [])
        group_data = next((g for g in groups if g["group_number"] == self._group_number), {})
        open_percent = group_data.get("open_percent", 0)
        #_LOGGER.debug("ManualNonITCClimate extra_state_attributes for group %s: open_percent=%s", self._group_number, open_percent)
        return {"open_percent": open_percent}

    def _calculate_open_percentage(self, current: float, target: float, ac_mode: str) -> int:
        """
        Calculate desired open percentage based on the absolute difference between
        current and target temperature.
        
        For COOL modes (e.g., "Cool", "AutoCool", "Auto", "Dry"):
        - If current <= target, return MIN_FAN_SPEED (to keep the fan running minimally).
        - Otherwise, linearly scale the difference so that when current equals AUTO_MAX_TEMP,
            the fan runs at MAX_FAN_SPEED.
            
        For HEAT modes (e.g., "Heat", "AutoHeat"):
        - If current >= target, return MIN_FAN_SPEED.
        - Otherwise, linearly scale the difference so that when current equals AUTO_MIN_TEMP,
            the fan runs at MAX_FAN_SPEED.
        """
        # Import constants from const.py
        from .const import MIN_FAN_SPEED, MAX_FAN_SPEED, AUTO_MAX_TEMP, AUTO_MIN_TEMP

        if ac_mode in ["Cool", "AutoCool", "Auto", "Dry"]:
            if current <= target:
                return MIN_FAN_SPEED
            fraction = min((current - target) / (AUTO_MAX_TEMP - target), 1.0)
            desired = int(MIN_FAN_SPEED + fraction * (MAX_FAN_SPEED - MIN_FAN_SPEED))
            return desired
        elif ac_mode in ["Heat", "AutoHeat"]:
            if current >= target:
                return MIN_FAN_SPEED
            fraction = min((target - current) / (target - AUTO_MIN_TEMP), 1.0)
            desired = int(MIN_FAN_SPEED + fraction * (MAX_FAN_SPEED - MIN_FAN_SPEED))
            return desired
        else:
            # For other modes, return the current open percentage from the device.
            group_obj = self._airtouch.GetGroupByGroupNumber(self._group_number)
            return getattr(group_obj, "OpenPercentage", MIN_FAN_SPEED)

    async def async_adjust_fan_speed(self) -> None:
        """
        Adjust the fan open percentage based on the current temperature (from the sensor)
        and the stored target temperature.
        
        Only adjust if the non-ITC zone is ON and its associated AC unit is ON.
        The desired open percentage is computed via _calculate_open_percentage,
        then rounded to the nearest 5%.
        """
        # Get the current group state from the API
        group_obj = self._airtouch.GetGroupByGroupNumber(self._group_number)
        if getattr(group_obj, "PowerState", "Off") == "Off":
            _LOGGER.debug("async_adjust_fan_speed: Group %s is off; skipping adjustment", self._group_number)
            return

        # Get the associated AC unit
        belongs_to = getattr(group_obj, "BelongsToAc", None)
        if belongs_to is None:
            _LOGGER.debug("async_adjust_fan_speed: Group %s has no associated AC; skipping adjustment", self._group_number)
            return

        ac_unit = self._airtouch.GetAcs()[belongs_to]
        if getattr(ac_unit, "PowerState", "Off") == "Off":
            _LOGGER.debug("async_adjust_fan_speed: Associated AC %s is off; skipping adjustment for group %s", belongs_to, self._group_number)
            return

        # Get current temperature from the sensor
        current_temp = self.current_temperature
        if current_temp is None:
            _LOGGER.debug("async_adjust_fan_speed: Current temperature unavailable for group %s; skipping adjustment", self._group_number)
            return

        # Calculate desired open percentage using _calculate_open_percentage.
        desired = self._calculate_open_percentage(current_temp, self._target_temp, getattr(ac_unit, "AcMode", "Fan"))
        # Round the result to the nearest 5%
        desired = round(desired / 5) * 5

        _LOGGER.debug(
            "async_adjust_fan_speed: For group %s, current_temp=%.1f, target_temp=%.1f, ac_mode=%s, computed desired open_percent=%s",
            self._group_number, current_temp, self._target_temp, getattr(ac_unit, "AcMode", "Fan"), desired
        )
        await self._airtouch.SetGroupToPercentage(self._group_number, desired)
        self.async_write_ha_state()

