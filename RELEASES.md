# 📝 Release Notes

All notable changes to AirTouch4 Advanced are tracked in this file.

## Version 2.1.0 (Pre-release)

- ✅ Fixed a bug where a failed connection to the AirTouch4 console could leave the integration's state tracking permanently frozen (coordinator and entity updates would crash on every cycle) until the integration was manually reloaded (#4)
- ✅ The integration now recovers automatically: repeated connection failures trigger a fresh reconnect, and a bad update cycle no longer crashes entities - they just keep their last known state until the next successful poll
- ✅ Fan entities (`fan.async_turn_on`/`async_turn_off`/`async_set_percentage`) now request an immediate state refresh after sending a command, instead of waiting up to the full 60s scan interval
- ✅ Added a lightweight listener for the AirTouch4 console's status broadcasts, so zone/AC changes made from the AirTouch app or a wall panel are reflected near-instantly instead of waiting for the next poll

## Version 2.0.3

- ✅ Nothing of note - Github user handle change only

## Version 2.0.2

- ✅ Added ability to reconfigure temperature sensors for non-ITC zones in climate mode
- ✅ Added translations for 11 languages (Spanish, German, French, Italian, Dutch, Swedish, Chinese Simplified, Chinese Traditional, Japanese, Korean, Portuguese)
- ✅ Fixed issues with setup and configuration flows
- ✅ Improved error handling and user feedback

## Version 2.0.1

- Initial HACS release
- Support for representing non-ITC zones as fans or climate entities
- Temperature-based automatic damper control
