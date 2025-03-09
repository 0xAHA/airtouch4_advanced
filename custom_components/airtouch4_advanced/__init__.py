"""The AirTouch4 integration."""
import logging

from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import AirtouchDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.FAN]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirTouch4 from a config entry."""
    _LOGGER.debug("Setting up AirTouch4 with config: %s", entry.data)

    host = entry.data[CONF_HOST]

    # Create AirTouch object and coordinator (pass an AirTouch instance, not host string)
    from airtouch4pyapi.airtouch import AirTouch  # ensure correct import
    airtouch = AirTouch(host)
    coordinator = AirtouchDataUpdateCoordinator(hass, airtouch)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.airtouch.GetAcs():
        raise ConfigEntryNotReady("No AC units discovered")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    async def adjust_all_manual_climates(now):
        manual_climates = hass.data[DOMAIN].get("manual_climates", [])
        for entity in manual_climates:
            await entity.async_adjust_fan_speed()
    
    async_track_time_interval(hass, adjust_all_manual_climates, timedelta(minutes=1))

    _LOGGER.debug("Forwarding entry setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AirTouch4 config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

