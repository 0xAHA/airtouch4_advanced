# 📝 Release Notes

All notable changes to AirTouch4 Advanced are tracked in this file.

## Version 2.1.4 (Pre-release)

- ✅ Added a guard for a false "off" reading variant reported in #4: a poll can report success with groups parsing correctly while an individual AC's own status is hollow (temperature reads `None` where the previous cycle had a real value). Compared per-AC rather than "any AC still looks fine", so a hollow read on one AC in a multi-AC system isn't masked by another AC that's still healthy. Also added the symmetric case of the AC list itself going from populated to empty, matching the existing zero-zones guard
- This is a mitigation, not a root-cause fix: the actual bad AC-status read happens inside `airtouch4pyapi`, a separate pinned dependency this repo doesn't maintain the source of, so it's outside what we can fix directly without forking or vendoring a modified copy of it — not something taken on here

## Version 2.1.3 (Pre-release)

- ✅ Fixed the broadcast listener re-triggering on its own polling echoes (#9) — the AirTouch4 console echoes status packets to every connected client, including the listener's own persistent connection, as a side effect of the coordinator's ordinary polling. This was a feedback loop: our poll's echo looked like an external change, triggered another refresh, whose echo triggered another. Two protocol-agnostic guards fix it without ever parsing packet contents: broadcasts arriving shortly after the coordinator's own poll activity are now recognised as that poll's echo and ignored, plus a minimum interval between listener-triggered refreshes as a backstop
- Added a `pytest` test suite (`tests/`) covering the echo-suppression/feedback-loop fix, now running in CI on every push and PR

## Version 2.1.2 (Pre-release)

- ✅ Setup now retries (`ConfigEntryNotReady`) instead of succeeding when the console returns no zones, which previously orphaned all zone/fan entities until a manual reload (#8)
- ✅ The coordinator now rejects an update cycle as failed if it parses zero zones when zones previously existed, instead of publishing that hollow read as valid state — a likely cause of the intermittent false "off" reads reported in #4
- The broadcast listener re-triggering on its own polling echoes (#9) is a separate, still-open issue — needs a deliberate fix design rather than a quick patch, since getting the suppression heuristic wrong risks silently dropping genuine external changes

## Version 2.1.1 (Pre-release)

- ✅ Fixed a crash in `AirtouchAC.hvac_modes`/`fan_modes` (`GetSupportedCoolingModesForAc`/`GetSupportedFanSpeedsForAc`) when the AirTouch client briefly returns partial state during a failed update cycle — these now fall back to the last known list instead of crashing the entity update, matching the guards added for `min_temp`/`max_temp` in 2.1.0 (#4)
- ✅ Added debug logging when the broadcast listener receives data, to help correlate broadcast timing against any state-parsing anomalies

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
