import logging
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Airtouch4 fans (i.e., PercentageControl zones)."""
    coordinator = config_entry.runtime_data
    info = coordinator.data

    fan_entities = []
    for group in info["groups"]:
        # Check if this zone is a PercentageControl zone
        zone_obj = coordinator.airtouch.GetGroupByGroupNumber(group["group_number"])
        if zone_obj.ControlMethod == "PercentageControl":
            fan_entities.append(AirtouchFan(coordinator, group["group_number"]))

    if fan_entities:
        async_add_entities(fan_entities)


class AirtouchFan(CoordinatorEntity, FanEntity):
    """Representation of an AirTouch PercentageControl zone as a fan."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    _attr_has_entity_name = True

    def __init__(self, coordinator, group_number):
        """Initialize the fan entity."""
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch
        self._attr_unique_id = f"fan_{group_number}"

        # Optional: Provide an initial object/dict for _unit
        initial_zone = self._airtouch.GetGroupByGroupNumber(group_number)
        self._unit = {
            "group_number": initial_zone.GroupNumber,
            "group_name": initial_zone.GroupName,
            "power_state": initial_zone.PowerState,
            "open_percent": initial_zone.OpenPercent,
        }

        # Device info so HA sees them as separate fan devices
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"fan_{group_number}")},
            manufacturer="Airtouch",
            model="Airtouch 4",
            name=initial_zone.GroupName,
        )

    @callback
    def _handle_coordinator_update(self):
        """Fetch updated data from coordinator for this fan zone."""
        # Retrieve fresh group data from self.coordinator.data
        all_groups = self.coordinator.data["groups"]

        if self._group_number >= len(all_groups):
            _LOGGER.error(
                "AirtouchFan: Group %s is out of range (Total groups: %s)",
                self._group_number,
                len(all_groups),
            )
            return

        # The coordinator stored group data in a dict
        fresh_unit = all_groups[self._group_number]

        # Log relevant data
        _LOGGER.debug(
            "AirtouchFan _handle_coordinator_update: Group %s, power_state=%s, open_percent=%s",
            self._group_number,
            fresh_unit.get("power_state", "Unknown"),
            fresh_unit.get("open_percent", 0),
        )

        # Convert from the coordinator data (dict) to our local _unit dict
        self._unit = {
            "group_number": fresh_unit["group_number"],
            "group_name": fresh_unit["group_name"],
            "power_state": fresh_unit.get("power_state", "Off"),
            "open_percent": fresh_unit.get("open_percent", 0),
        }

        self.async_write_ha_state()

    @property
    def name(self):
        """Return the fan's name."""
        return self._unit["group_name"]

    @property
    def is_on(self) -> bool:
        """Return True if fan is on."""
        return self._unit["power_state"] == "On"

    @property
    def percentage(self) -> int | None:
        """Return the current fan speed percentage."""
        # Because we stored open_percent in self._unit
        return self._unit["open_percent"]

    @property
    def percentage_step(self) -> int:
        """Return the 5% increments for the fan speed."""
        return 5

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn the fan on with optional speed."""
        _LOGGER.debug(
            "AirtouchFan: Turning ON group %s with percentage=%s",
            self._group_number,
            percentage,
        )
        await self._airtouch.TurnGroupOn(self._group_number)

        if percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs):
        """Turn the fan off."""
        _LOGGER.debug("AirtouchFan: Turning OFF group %s", self._group_number)
        await self._airtouch.TurnGroupOff(self._group_number)

    async def async_set_percentage(self, percentage: int):
        """Set the fan speed, turning off if 0% is requested."""
        if percentage == 0:
            await self.async_turn_off()
        else:
            _LOGGER.debug("AirtouchFan: Setting group %s to %s%%", self._group_number, percentage)
            await self._airtouch.SetGroupToPercentage(self._group_number, percentage)

        self.async_write_ha_state()
