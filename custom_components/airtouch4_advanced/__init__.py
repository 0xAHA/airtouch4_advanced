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

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the AirTouch4 component."""
    _LOGGER.debug("Setting up AirTouch4 integration")
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirTouch4 from a config entry."""
    _LOGGER.debug("Setting up AirTouch4 with config: %s", entry.data)
    _LOGGER.debug("Options: %s", entry.options)

    host = entry.data[CONF_HOST]
    
    # First try to get from options, then fall back to data for backward compatibility
    setup_mode = entry.options.get("setup_mode") or entry.data.get("setup_mode")
    sensor_map = entry.options.get("nonitc_sensors") or entry.data.get("nonitc_sensors", {})

    _LOGGER.debug("Setup mode: %s", setup_mode)
    _LOGGER.debug("Sensor map: %s", sensor_map)

    # Create AirTouch data coordinator
    try:
        from airtouch4pyapi.airtouch import AirTouch
        
        airtouch = AirTouch(host)
        coordinator = AirtouchDataUpdateCoordinator(hass, airtouch)
        await coordinator.async_config_entry_first_refresh()

        if not coordinator.airtouch.GetAcs():
            _LOGGER.error("No AC units discovered for %s", host)
            raise ConfigEntryNotReady("No AC units discovered")

    except Exception as err:
        _LOGGER.exception("Error setting up AirTouch integration: %s", err)
        raise ConfigEntryNotReady(f"Failed to connect to AirTouch at {host}: {err}")

    # Initialize data structure in domain data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "setup_mode": setup_mode,
        "sensor_map": sensor_map
    }
    
    # Initialize manual_climates list if it doesn't exist
    if "manual_climates" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["manual_climates"] = []

    # Set up periodic adjustment for manual climate entities
    async def adjust_all_manual_climates(now):
        manual_climates = hass.data[DOMAIN].get("manual_climates", [])
        _LOGGER.debug("Running periodic adjustment for %d manual climates", len(manual_climates))
        for entity in manual_climates:
            try:
                await entity.async_adjust_fan_speed()
            except Exception as err:
                _LOGGER.error("Error adjusting fan speed for %s: %s", entity.entity_id, err)

    # Register the time interval handler
    cancel_interval = async_track_time_interval(
        hass, 
        adjust_all_manual_climates, 
        timedelta(minutes=1)
    )
    
    # Store the cancel function so we can clean up on unload
    hass.data[DOMAIN][entry.entry_id]["cancel_interval"] = cancel_interval

    # Forward the entry setup to platforms
    _LOGGER.debug("Forwarding entry setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register the reload handler
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AirTouch4 config entry."""
    _LOGGER.debug("Unloading config entry for host: %s", entry.data.get(CONF_HOST))
    
    # Cancel the periodic interval handler if it exists
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        cancel_interval = hass.data[DOMAIN][entry.entry_id].get("cancel_interval")
        if cancel_interval:
            cancel_interval()
    
    # Unload the platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Clean up the entity data
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
        # Clean up manual_climates list - filter out entities from this entry
        if "manual_climates" in hass.data[DOMAIN]:
            # This assumes that each entity has an entry_id attribute referencing the config entry
            # If that's not the case, you might need a different method to identify which entities to remove
            hass.data[DOMAIN]["manual_climates"] = [
                climate for climate in hass.data[DOMAIN]["manual_climates"]
                if getattr(climate, "entry_id", None) != entry.entry_id
            ]
    
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload AirTouch4 config entry."""
    _LOGGER.info("Reloading config entry for host: %s", entry.data.get(CONF_HOST))
    _LOGGER.debug("Current entry options: %s", entry.options)
    
    # Store the latest options and sensor mapping for persistence
    setup_mode = entry.options.get("setup_mode") or entry.data.get("setup_mode")
    sensor_map = entry.options.get("nonitc_sensors") or entry.data.get("nonitc_sensors", {})
    
    _LOGGER.debug("Reload with setup_mode: %s", setup_mode)
    _LOGGER.debug("Reload with sensor_map: %s", sensor_map)
    
    # Unload the existing entry
    await async_unload_entry(hass, entry)
    
    # Set up the entry again with updated configuration
    await async_setup_entry(hass, entry)