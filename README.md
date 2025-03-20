# AirTouch4 Advanced

Custom version of the official AirTouch4 Integration from Home Assistant.

⚠️ **Disclaimer:** This integration is neither officially supported by AirTouch nor Home Assistant. **Use at your own risk.** ⚠️

## Objective

The primary issue addressed by this custom integration is the incorrect representation of zones without Individual Temperature Control (ITC) in the core integration. Specifically:

* Fictional current temperature values (e.g., 154.7°C) were displayed for zones without ITC when represented as Climate entities.
* Lack of visibility and control over fan speed/percentage (damper open/close percentage) for these zones due to their representation as Climate entities.

## Result

This version of the integration now determines whether a zone has an ITC.

* Zones **with** ITC: No changes; they continue to be created as Climate entities.
* Zones **without** ITC can be created as:
  * **Fan Entities:**
    * On/Off control
    * Fan speed control (in percent, with 5% increments, matching the AirTouch system interface)
    * These fan zones behave like the AirTouch panel/app, showing as "On" if enabled, even when the main AC system is off.
  * **Climate Entities (with temperature sensor):**
    * Zones created as climate entities
    * Current temperature based on a user-configured temperature sensor
    * Automated fan/damper percentage control based on the target temperature

## Installation

As this is a custom version of an official integration, the installation process is manual but straightforward.

### HACS Installation

This custom integration is available in the [Home Assistant Community Store (HACS)](https://hacs.xyz/).

**Steps:**

1. Install HACS if you haven't already.
2. Open HACS in Home Assistant.
3. Search for "Airtouch4 Advanced".
4. Click the download button (⬇️).

### Manual Installation

1. Download this repository.
2. Create a `custom_components/airtouch4_advanced` folder in your Home Assistant config directory.
3. Copy the downloaded files into the new folder.

   ```
   {path_to_your_config}
   ├── configuration.yaml
   └── custom_components
       └── airtouch4_advanced
           └── translations
           |   └── en.json
           ├── __init__.py
           ├── climate.py
           ├── config_flow.py
           ├── const.py
           ├── coordinator.py
           ├── fan.py
           └── manifest.json
   ```
4. Restart Home Assistant.

## Configuration

1. In Home Assistant, go to **Settings > Devices & Services** and click **Add Integration**.
2. Search for "AirTouch4". The custom integration should have a red "custom integration" box icon.
   ![1742435174300.png](./1742435174300.png)
   
3. The integration will attempt to automatically detect the IP address of your AirTouch4 system. If this is not successful, enter the IP address of your AirTouch4 system (tablet/panel).

   ![Enter IP Address](./1741414596830.png)
  
4. Select the zone configuration mode:

   ![1742434942911.png](./1742434942911.png)

   **Default Mode:** Configures all zones as standard climate entities.

   **Non-ITC zones as Fans:** Creates zones without ITC as fan entities, providing percentage control similar to the AirTouch app.

   **Non-ITC zones as Climate:** Allows selecting a temperature sensor for zones without ITC, creating climate entities that automatically adjust the fan/damper percentage based on the target temperature.

   ![1742435054772.png](./1742435054772.png)
5. The integration will add the main Aircon system (likely labelled "AC 0") and climate zones or fans based on the selected setup mode. In all cases, zones with an ITC will continue to be created as standard climate zones.

## Example Dashboard

The following examples show dashboards for each setup mode:

1. "Air-Con" is the main "AC 0" entity, providing HVAC mode and fan speed control regardless of the setup mode.
2. "Master," "Kitchen," and "Juni" are example zones **with** ITC. Only target temperature can be controlled. These zones are created as climate zones in all setup modes.
3. "Ali," "George," "Study," and "Rumpus" are example zones **without** ITC and are represented differently based on the setup mode.
4. Fan zones maintain the last set fan speed, matching the AirTouch4 panel/app (the app doesn't show the percentage when the zone is off).

**Default Mode:** All zones are created as climate zones, but note the false 154.7°C current temperature for zones without ITC.

![Default Mode Example](./1741415638843.png)

**Non-ITC zones as Fans:** Fan zones maintain the last set fan speed, mirroring the AirTouch app functionality.

![Fan Mode Example](./1741415649486.png)

**Non-ITC zones as Climate entity:** Zones without ITC are climate zones with real current temperature values based on selected sensors. The "Ali" zone shows an example of the open percentage (fan speed) attribute.

      ![Climate Entity Mode Example](./1741415656794.png)

### To-Do

* Monitor and improve automatic damper control for non-ITC zones configured as climate entities.
* Improve HA interface refresh speed when reading parameters. Expect some delay in the interface update.

### Disclaimer

These changes work with a single ducted system. Functionality with multiple AC systems should still operate as normal, but it's untested. This integration assumes that all non-ITC zones only have ON (fan-only) and OFF modes.
