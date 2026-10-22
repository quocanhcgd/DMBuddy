# Creality K3 integration notes

Updated: 2026-10-22

## Research findings

- Creality's official K3 page describes a nozzle-changing multi-material/multicolor printer, with 4.8 second nozzle changes and a multi-material workflow: <https://www.creality.com/products/k3>.
- Printago's Creality setup guide describes connecting supported Klipper-based Creality machines through Moonraker, with `7125` as the default Moonraker port: <https://docs.printago.io/docs/connecting-printers/creality>.
- The same guide and Creality community web-interface documentation mention `4408` on some Creality firmware/UI setups. This does not prove that K3 exposes Moonraker JSON on `4408`.
- The product page does not publish a local control API, Moonraker endpoint, authentication method, camera URL, file format contract, or nozzle-change command contract. Do not infer these from K1/K2 behavior.
- Printbuddy already has a shared Moonraker provider for `klipper`, `mainsail`, and `fluidd`. It implements connection verification via `server/info`, status through Klipper object queries, G-code file upload/list/start, pause/resume/cancel, common heater/fan controls and Moonraker webcam discovery.
- Add Printer's Moonraker discovery now checks configured ports (default 7125, 80 and 4408). A hit must return Moonraker-identifying JSON; the extra port is a candidate only, not proof K3 exposes Moonraker there. The scan remains limited to the user-selected subnet and ports can be edited.
- The Moonraker scanner now shares one bounded HTTP client across the scan (32 connections, batches of 32) instead of creating a client for every host. Scanning the user's confirmed `192.168.0.0/24` completed all 254 usable addresses and found the K3 at `192.168.0.158` on `7125`; another Moonraker host at `.38` was also found. A direct read-only request to `192.168.0.158:4408/server/info` also returned HTTP 200 with Moonraker JSON. This confirms reachability on both ports and subnet discovery on the current host and LAN, without claiming the connection-pool change is the only possible cause of the earlier miss.
- Existing Creality K2-specific behavior is deliberately model-gated: CFS macros, CFS status interpretation, and proprietary camera paths. K3's nozzle changer is not the K2 CFS and must not reuse those paths.

## Current support and verification

`Creality K3` is selectable under the existing `Creality Klipper` model group. Moonraker discovery includes `4408` as a candidate in addition to `7125` and `80`, reuses a bounded HTTP client for subnet scans, and accepts only Moonraker-shaped `server/info` JSON. The K3 was observed responding at both `192.168.0.158:7125` and `192.168.0.158:4408`; a complete scan of `192.168.0.0/24` found it. It routes through the existing Klipper/Moonraker provider when selected. This verifies API reachability and discovery only; print lifecycle and nozzle-changer support remain unverified.

Creality model image mappings now cover the listed Ender-3, Ender-5 Plus, CR-10S Pro, K1/K1C/K2 Plus models and K3. K3 artwork is bundled from Creality's official K3 product page (<https://www.creality.com/products/k3>) in both frontend and runtime static asset directories.

Verification for the scanner fix: Moonraker scanner unit `12 passed`; Ruff passed; a live scan of `192.168.0.0/24` returned `192.168.0.158` and completed at `254/254`; direct GET on port `4408` returned HTTP 200 with Moonraker JSON. Existing catalog verification remains Moonraker scanner `11 passed`, K3 model catalog `1 passed`, Ruff, Python compileall, TypeScript and locale parity passed. The Add Printer page-level test previously could not load because the installed `react-router-dom` CommonJS entry requires an ES module from `react-router`; the pure catalog test covers the changed model data without that router setup.

The scan was also repeated from the running Add Printer UI: `192.168.0.158` appeared and selecting it filled the IP, Moonraker URL, and K3 model. Selection now clears the prior scan-complete state so the UI cannot continue showing a stale no-results/all-configured message after results are dismissed. Frontend TypeScript passed; the focused Add Printer component test remains blocked at collection by the existing `react-router-dom` CommonJS / `react-router` ESM dependency error.

## Integration sequence

1. **Complete:** Confirm the printer's LAN IP and observe Moonraker `server/info` on `7125`; full `192.168.0.0/24` discovery found the K3.
2. **Next:** Verify read-only `printer/objects/query` for `toolhead`, `extruder`, `heater_bed`, `print_stats`, and `virtual_sdcard`. Record sanitized object names and response shapes; never record access tokens.
3. Verify ordinary single-file G-code list/upload/start and pause/resume/cancel with a supervised, non-production print. Capture pre-state, one command, and readback. Do not retry a command after an ambiguous timeout.
4. Check temperatures, fan controls and camera independently. Add K3-specific camera handling only after observing a documented/firmware-confirmed endpoint; retain generic Moonraker webcam discovery as fallback.
5. Research the nozzle-change mechanism separately. Determine whether slicer output uses ordinary `T<n>` tool changes or a K3-specific macro/API, how active nozzle identity and temperatures appear in Moonraker objects, and whether tool-change G-code is already embedded in sliced files. Until verified, do not expose K3 nozzle selection, material mapping, or special macros in Printbuddy.
6. Add captured, sanitized fixtures and provider/UI regression tests for verified behavior. Keep unsupported capabilities explicit and avoid interpreting K2 CFS data as K3 tooling.

## Evidence status and next input

- Source evidence: official product page for product behavior; existing Printbuddy Moonraker code for generic API support.
- `hardware_verified=true` for Moonraker reachability and subnet discovery only: `server/info` returned Moonraker JSON at `192.168.0.158:7125` and `:4408`, and a full `/24` scan found the host. `hardware_verified=false` for ordinary print lifecycle, camera behavior, and K3 nozzle-changing behavior.
- Next: use Add Printer to enroll the discovered printer, verify read-only Klipper object names and ordinary G-code list/upload/start/pause/resume/cancel under supervision. Research nozzle changing separately after capturing actual slicer output and firmware object/API behavior. Do not include passwords or tokens in project notes.

## Printer artwork refresh checkpoint — 2026-10-22

- Existing printer records resolve artwork from their saved `model` using `getPrinterImage`; no re-add or database migration is needed when the model already identifies as `Creality K3`.
- `Creality K3` and the short alias `K3` map to `/img/printers/creality-k3-v2.png`. The versioned filename avoids stale browser/proxy cache entries for the earlier `creality-k3.png` path.
- The image is bundled in both `frontend/public/img/printers/` and `static/img/printers/`. The running Vite server (`5174`) and app server (`8000`) both returned HTTP 200 for the versioned asset; the Printers page DOM shows the existing `Creality K3` record.
- Verification: image/model tests `20 passed`; TypeScript `tsc --noEmit` passed. A full frontend suite was attempted but stopped after unrelated existing `SystemHealthPanel` locale assertions failed; it is not evidence of a printer artwork regression.
- If an already-open browser still shows the previous artwork, reload the Printers page once (hard reload if the old image remains). Confirmed target URL: `/img/printers/creality-k3-v2.png`.

## K3 configuration and live Moonraker evidence — 2026-10-22

### Files reviewed

- User supplied `printer.cfg`, `factory_printer.cfg`, `gcode_macro.cfg`, `printer_params.cfg`, `box.cfg`, `motor_control.cfg`, and `moonraker.conf`. No credentials or tokens were found in these files.
- The active-looking `printer.cfg` includes `sensorless.cfg`, `gcode_macro.cfg`, `printer_params.cfg`, and `box.cfg`; all four included files are now supplied. `motor_control.cfg` is not included by `printer.cfg` (its include is commented out), and its header says 350 mm while the active printer profile says 260 mm. Do not import it as active K3 configuration without confirming its origin.
- `printer.cfg` defines four heater/extruder objects (`extruder`, `extruder1`, `extruder2`, `extruder3`), a four-nozzle `[nozzle_manager]`, a `nozzle_check` section, `heater_bed`, `virtual_sdcard`, and fan output pins. The config supports multiple heaters.
- Moonraker listens on port `7125` at `0.0.0.0`; upload size is configured to 1024 MiB. File manager disables queued uploads and object processing. Authorization has `force_logins: False` and trusts RFC1918 LAN ranges; do not change these settings as part of printer integration.

### Live, read-only verification

- Queried `GET /printer/objects/list`, `GET /printer/objects/query` and `GET /printer/gcode/help` on the enrolled K3 at `192.168.0.158:7125`. No G-code script or other side-effecting request was sent.
- Runtime exposes `toolhead`, `extruder` through `extruder3`, `heater_bed`, `print_stats`, `virtual_sdcard`, `display_status`, `pause_resume`, `nozzle_manager`, `box`, `filament_rack`, and `filament_switch_sensor filament_sensor`.
- Runtime `nozzle_manager` contains four nozzle entries with `id`, `diameter`, `loaded`, `material_loaded`, `movement`, `state`, `connection`, and `offset_xyz`, a `selected` index, four heater readings under `nozzle_temp`, print flow, and PID-check status. The observed idle sample had `selected=-1`; do not infer that nozzle 0 is active when the device reports no selected nozzle.
- Runtime `toolhead.extruder` was `extruder`; all four heater objects returned temperatures and targets. The live sample had an idle printer state, bed/nozzle targets at zero, and no active file.
- Runtime `box` identified its attached station as `CFS-Nano`, exposed `T1A` through `T4D` in its material map, and reported station state/connectivity and material arrays. Preserve this as a K3/CFS-Nano data contract; do not silently model it as Bambu AMS or assume it is the K2 Plus CFS implementation.
- Runtime `gcode/help` confirms macros such as `START_PRINT`, `END_PRINT`, `PAUSE`, `RESUME`, `CANCEL_PRINT`, `CHANGE_T`, `LOAD_NOZZLE`, `UNINSTALL_NOZZLE`, `BOX_LOAD_MATERIAL`, `BOX_QUIT_MATERIAL`, and `M8200`. It does not list `T0`-`T3`, `NOZZLE_REPLACE`, or `NOZZLE_LOAD` as callable commands in that help response. Some are referenced internally by macros/firmware code, which is not proof that Printbuddy should call them directly.
- `START_PRINT` performs homing, nozzle cleaning, bed heating, a `T0` call, nozzle heating, and `BOX_START_PRINT`. `CHANGE_T`, `LOAD_NOZZLE`, `UNINSTALL_NOZZLE`, box load/quit macros, and `M8200` can move axes, change nozzle, heat, cut, feed, or retract filament. Treat them as side-effecting machine operations; do not use them for status discovery or automatic retries.
- The supplied `sensorless.cfg` overrides `G28`. Homing may invoke `HOMING_LOAD_NOZZLE DEFAULT=0`; on initial Z homing it also moves to the box extrude position, runs pressure checks and `BOX_NOZZLE_CLEAN`, then performs the Z homing routine. Supporting the app's Home action therefore requires K3-specific safety review and post-command readback; do not assume generic `G28` semantics or retry after an ambiguous timeout.
- `sensorless.cfg` enables Klipper `force_move`; its homing helpers use `FORCE_MOVE` in some states. Printbuddy must not expose these calibration/low-level commands as generic controls.

### Integration decision and next verification

- The existing Moonraker provider already knows the four generic extruder objects, but its generic provider status polling queries only the primary heater in the common status path. Add a model-specific K3 read-only adapter for `nozzle_manager` and four extruder heaters, keeping generic Klipper behavior unchanged.
- The current Creality box parser translates `box.T1`..`T4` to CFS-shaped tray data. For K3, validate `type=CFS-Nano`, tray mapping, material/color codes and active-nozzle relationship before exposing it as normalized filament state; do not infer active tool from the box's active slot.
- Build sanitized fixtures from the observed `nozzle_manager` and `box` object shapes, then add tests for absent/invalid optional objects and the `selected=-1` idle case.
- Configuration review is now complete for every include named in the supplied `printer.cfg`; the 260 mm active profile remains distinct from the unreferenced 350 mm `motor_control.cfg`.
- Next physical evidence needed before nozzle actions: query the macro variable/status objects for `CHANGE_T_PARAM.current_num` and runtime nozzle selection after a user-operated nozzle change in Fluidd; inspect one actual slicer-produced K3 G-code file for tool-change syntax and start/end macro parameters. Capture before/after read-only snapshots. Do not ask the user to run calibration, load/unload, cutting, or nozzle replacement as a diagnostic.
- Ordinary print start/pause/resume/cancel, file upload integrity, fan semantics, camera endpoint, and nozzle/material operations remain individually unverified on this firmware despite the live read-only object discovery.

### Read-only K3 nozzle telemetry checkpoint — 2026-10-22

- Moonraker provider now uses a model-gated K3 status adapter for `K3` / `Creality K3`. It queries only advertised `toolhead`, `nozzle_manager`, and four extruder objects; other Moonraker models keep the existing path.
- The adapter exposes all four nozzle heater temperatures/targets through the existing four-nozzle temperature keys and fills the existing nozzle diameter list. It carries a sanitized `raw_data.creality_k3` snapshot with selected nozzle, nozzle loaded/state/connection/offset fields, and discovered station type names.
- A reported `nozzle_manager.selected=-1` remains `active_extruder=-1` (unknown); it is not guessed from `toolhead.extruder` or the active CFS material slot.
- K3's `box` object remains available as raw read-only data, but the K2 Plus CFS-to-AMS normalizer is model-gated off for K3. This prevents CFS-Nano slot/material state from accidentally enabling the K2 M8200 load/unload/start-print path before K3 semantics are proven.
- No G-code was sent. There is no UI control for nozzle replacement/loading or CFS-Nano material actions added in this checkpoint. The existing temperatures component can render four reported heaters.
- Verification: Moonraker provider selected unit suite `28 passed`; Ruff, compileall and `git diff --check` passed.
- Next: compare a user-performed nozzle change using before/after read-only Moonraker snapshots and inspect a real K3 slicer G-code file. Only then design a separate K3 CFS/nozzle command adapter with delivery-unknown reconciliation and supervised hardware tests.

### Read-only Fluidd and active-config checkpoint — 2026-10-22

- Opened the printer web UI at `http://192.168.0.158:4408/`; it serves Fluidd `v1.30.0-f3e4ac3`. Port 80 returns 404. Fluidd UI currently displays `No moonraker connection` for `http://192.168.0.158:7125`, while direct read-only Moonraker GET requests to that endpoint succeed. The UI connection problem is unresolved; do not interpret it as Moonraker being offline.
- Retrieved config files through Moonraker's read-only `GET /server/files/config/{filename}` and compared SHA-256 with the user-provided Downloads copies. `printer.cfg`, `sensorless.cfg`, `gcode_macro.cfg`, `printer_params.cfg`, `box.cfg`, `factory_printer.cfg`, and `motor_control.cfg` match byte-for-byte after HTTP text decoding. Moonraker's config root also lists timestamped printer backups; `motor_control.cfg` is present but remains excluded in `printer.cfg`.
- Runtime query again confirms all four nozzle records and heaters. In this later idle snapshot, `nozzle_manager.selected=-1`, `toolhead.extruder=extruder`, and `gcode_macro CHANGE_T_PARAM.current_num=0` simultaneously. These fields do not agree, so active nozzle identity must remain unknown until an observed, user-operated tool change yields a reliable state contract.
- The live `box` object reports `type=CFS-Nano`, `is_online=true`, `state=connect`; only `T1A` maps to a populated material entry (`PLA`) in this snapshot and all other T2-T4 map entries are null. This is a read-only sample, not enough to normalize CFS-Nano into AMS trays or infer nozzle-to-slot pairing.
- The active firmware exposes many extra help commands, including lower-level motor, calibration, nozzle and EEPROM commands. Their presence in `gcode/help` is not evidence that generic Printbuddy controls should expose them. No G-code, config write, restart, or macro invocation was issued.
- Next: resolve the Fluidd-to-Moonraker UI connection only if it is needed for observing a user-performed nozzle change; capture the before/after object values and inspect an actual slicer-produced K3 G-code file. Keep nozzle selection/CFS actions disabled until those observations establish a non-conflicting contract.

### Fluidd connection and slicer G-code checkpoint — 2026-10-22

- After a fresh page load, Fluidd connected successfully and showed the dashboard in `READY`; the Configuration view listed the same active config and backup files as Moonraker. The earlier `No moonraker connection` banner was transient in this session. `OPTIONS /server/info` with Origin `http://192.168.0.158:4408` returned 204 and allowed that exact origin; a read-only WebSocket handshake to `/websocket` also opened and returned a Moonraker notification. No Moonraker config change was needed.
- Read the existing `High-Speed 4-Color Benchy_PLA_28m43s.gcode` by bounded HTTP byte ranges (no upload/start). Header identifies Creality Print `V7.2.0039.5244`. Start uses `START_PRINT EXTRUDER_TEMP=220 BED_TEMP=55`; file contains tool commands `T0`, `T1`, `T2`, and `T3`, with `M104 ... Tn` preheat before `T1`-`T3`, and ends with `END_PRINT`. The inspected file portion contains no direct `CHANGE_T`, `BOX_LOAD_MATERIAL`, `BOX_QUIT_MATERIAL`, `LOAD_NOZZLE`, or `UNINSTALL_NOZZLE` calls.
- This establishes actual slicer syntax (`T<n>`) and macro parameters for one Creality Print sample, but not that those commands update `nozzle_manager.selected` or `CHANGE_T_PARAM.current_num` consistently. This G-code was inspected only; it was not started or sent to the printer.
- A new read-only baseline while the printer was `standby` had no active file, `nozzle_manager.selected=-1`, `toolhead.extruder=extruder`, and `gcode_macro CHANGE_T_PARAM.current_num=0`. The prior completed print in `virtual_sdcard.cur_print_data` was a single-color Benchy, not the inspected 4-color file; do not treat it as evidence of a physical T1-T3 transition.
- Next: use the state-query API before and after a user-operated nozzle selection in Fluidd (no Printbuddy-issued action), then correlate `selected`, `toolhead.extruder`, `CHANGE_T_PARAM.current_num`, heater targets, and nozzle loaded/state fields. Inspect one 4-color G-code's complete tool-change context before accepting `T<n>` as the integration contract. Keep CFS material actions gated.

### User-operated heater test checkpoint — 2026-10-22

- After the user reported trying heater controls, read Moonraker's read-only `server/temperature_store` history (600 samples per heater) and current `printer/objects/query` state. `extruder1` and `extruder2` history both showed a `40 C` target; measured peaks were about `49.3 C` and `46.5 C`, followed by cooling. At the current query both targets were `0 C`; `extruder` and `extruder3` had no nonzero targets in the retained history.
- Nozzle identity fields did not change: `nozzle_manager.selected=-1`, `toolhead.extruder=extruder`, and `CHANGE_T_PARAM.current_num=0`; print state remained `standby` with no active file. This confirms a heater-control/temperature-reporting exercise, not a nozzle-selection test.
- The observed peak temperatures exceeded the recorded `40 C` target. Preserve this as a measured detail for review; do not infer exact heater control dynamics from one short history window. No new heating command was issued by Printbuddy.
- Next: keep the verified four-heater telemetry path, and separately capture nozzle-selection state after the user uses the K3's normal nozzle-change workflow. Do not use heating as a proxy for selecting or loading a nozzle.

### User-operated nozzle selection checkpoint — 2026-10-22

- User performed a nozzle-selection operation through the printer's normal workflow. Before the operation, the captured standby baseline was `nozzle_manager.selected=-1` and all four `loaded` flags were `0`.
- Two read-only Moonraker snapshots after the operation, about 23 seconds apart, both reported `nozzle_manager.selected=2`; exactly nozzle ID 2 had `loaded=1`, while IDs 0, 1, and 3 had `loaded=0`. `nozzle_manager.current_extruder.temperature` matched `extruder2` at approximately 33.5 C. Printer remained `standby`, with no active G-code file and all heater targets at zero.
- The generic `toolhead.extruder` still reports `extruder`, and `gcode_macro CHANGE_T_PARAM.current_num` still reports `0`. For K3 selected-nozzle readback, use the model-specific `nozzle_manager.selected` and preserve the other fields as independent raw diagnostics; do not overwrite or conflate them. Existing provider already maps the selected value to `active_extruder` and keeps raw K3 nozzle details.
- This verifies read-only selected-nozzle telemetry on the physical K3 for one manual selection (ID 2). It does not verify that G-code `T0`-`T3` causes the same transition, nor any start-print, nozzle load/unload, replacement, or CFS material action. Keep those command paths gated until separately tested with an appropriate supervised workflow.
- Next: add a regression fixture for the observed selected=2/loaded=2 state if provider behavior changes; otherwise proceed with read-only UI reporting for active nozzle and test `T<n>` only during an explicitly supervised real print. Do not invoke K3 macros as diagnostics.

### K3 read-only printer-card guard — 2026-10-22

- The K3 printer card ignores generic `ams` and `vt_tray` payloads and their cached values. This prevents legacy/generic tray data from being presented as CFS-Nano inventory.
- K3 cards suppress the generic “Loaded spool” inventory picker because the observed firmware state does not establish a mapping from inventory spool to the manually selected nozzle. The selected nozzle and its temperature remain visible through the existing K3 four-nozzle/active-extruder display.
- Regression coverage asserts that a K3 card with injected AMS-A/PLA and VT/PETG payloads still shows E2 Active but shows neither those generic material entries nor an unrelated loaded-spool picker.
- CFS-Nano remains read-only and separate from AMS/VT tray data. The typed status payload exposes station state and four A-D slots only for each station whose reported type is CFS-Nano; absent material metadata remains null for the UI to show as Unknown. No CFS load/unload actions or nozzle-to-slot mapping were added.
- Verification for the display guard: `npx tsc --noEmit`, `npm run build`, and `git diff --check` passed; focused Vitest could not collect because `react-router-dom` CommonJS requires `react-router` ESM, so zero UI tests ran. See the following dedicated payload checkpoint for end-to-end checks.
- Next: verify the status payload against a fresh read-only Moonraker query and test G-code `T<n>` only during an explicitly supervised physical print. No command was sent as part of this checkpoint.

### Read-only CFS-Nano payload and card — 2026-10-22

- The K3 Moonraker adapter creates `creality_k3.cfs_nano` only when a reported station type equals `CFS-Nano`. It returns slot data only for stations identified as CFS-Nano, with four A-D slots per detected station (the current single T1 CFS-Nano therefore produces T1A-T1D, not 16 guessed slots). Fields are allowlisted material name, bounded material code, and normalized hex color; serial numbers, vendor payloads, remaining length, active filament, and raw box data are not included.
- REST `PrinterStatus` and WebSocket status now carry the separate `cfs_nano` field. The frontend renders it only for K3 cards; unknown material metadata is labeled “Unknown”. It is excluded from generic AMS/VT data, inventory spool selection, and queue filament matching.
- Tests cover K3 normalization, four slots for a single CFS-Nano station (excluding a different station type), T1A PLA/color, unknown T1B, WebSocket separation, schema slot validation, and the card rendering contract.
- Verification: selected backend provider, WebSocket serialization, and schema suites passed `183` tests with `pytest --noconftest`; Ruff, Python compileall, TypeScript (via build), frontend production build, and `git diff --check` passed. Build warns Node 20.12.2 is below Vite's 20.19+ recommendation. Focused Vitest could not collect because `react-router-dom` CommonJS requires `react-router` ESM (zero UI tests ran). Normal pytest startup is blocked by installed `pyftpdlib` lacking `TLS_FTPHandler` in the shared service conftest.
- Next: perform a read-only status refresh against the enrolled K3 and confirm visible CFS-Nano state/slot values. Keep material controls and nozzle-to-slot inference disabled.

### CFS-Nano card layout alignment — 2026-10-22

- The initial CFS-Nano presentation was a standalone card section after temperatures, which did not match the existing Filaments/AMS placement or visual grouping.
- CFS-Nano now renders inside the existing Filaments section and the same two-column module grid used by AMS units. Its module uses the shared dark panel/border spacing, a four-column slot grid, and the existing `FilamentSlotCircle` color/number treatment. The active slot is not highlighted because the observed K3 active nozzle does not establish CFS slot-to-nozzle state.
- Regression assertions verify CFS-Nano is nested under `printer-card-section-filaments` and there is no standalone `cfs-nano` section. `npx tsc --noEmit`, production build, and `git diff --check` pass. Focused Vitest remains blocked at collection by the installed React Router CommonJS/ESM conflict.
- Next: reload the app and visually confirm the section placement on the K3 card. No printer command or status mutation was issued.
