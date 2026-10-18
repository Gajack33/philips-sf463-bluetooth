# Philips SF463 Bluetooth front-key firmware

Experimental firmware for the **Philips YKF463-001 / SF463** double-sided remote, tested with a **Philips 55OLED804/12**. It enables ordinary front buttons to use the remote's existing Bluetooth consumer-HID path, alongside the rear Bluetooth keyboard.

**Current tested build: `GVK1EH_B002FFv.06.07`.** This is a local, unofficial version number, not a Philips release. The exact binary in this repository was installed on the test remote.

## Observed result

Before the modification, the rear keyboard worked over Bluetooth, but the front arrows did not work with the infrared emitter covered. In normal use, the front only worked reliably when the remote was held on its edge. New batteries and re-pairing did not resolve the problem.

After installing 06.07:

- Front navigation and the rear keyboard worked with the infrared emitter covered.
- Front Left/Right press and release events were captured through the TV's Bluetooth consumer-input path, with no matching infrared events.
- The owner confirmed that the remote could also wake the TV with the infrared emitter covered.
- After all temporary diagnostic Bluetooth clients had been stopped, a single brief front Right press worked in the normal holding position after **60 seconds of inactivity**.

These observations come from **one remote and one TV**, on 2026-10-18. They do not establish compatibility with other revisions, long-term reliability, or wake after hours of deep standby. The infrared transmitter is **not disabled**, and every physical key has not been verified on hardware.

## Compatibility and risks

Tested combination:

| Component | Tested version |
| --- | --- |
| Remote | Philips YKF463-001 / SF463; casing marking `ABS HB SF463` |
| Original remote firmware | `GVK1EH_B002FFv.06.05` |
| Modified remote firmware | `GVK1EH_B002FFv.06.07` |
| TV | Philips 55OLED804/12 |
| TV software | `TPM191E_R.211.000.103.000` |
| Native updater | `com.easy.oad` 2.0.27 |

**Flashing can permanently disable the remote.** A stock firmware file is included, but it is not a full backup of the bootloader, calibration, or pairing data. Software recovery requires the remote to remain reachable over Bluetooth; a hardware programmer may be necessary if it no longer boots or connects. Recovery has not been demonstrated.

Do not infer compatibility from a similar-looking casing alone. The builders require the exact original SHA-256 and instruction bytes. No bootloader unlock or signature bypass is included.

## Files

| Path | Purpose |
| --- | --- |
| [`firmware/RCFW/`](firmware/RCFW/) | The tested 06.07 image, ready for the native USB updater |
| [`firmware/original/`](firmware/original/) | Unmodified 06.05 image extracted from a TV recovery package |
| [`reproduction/`](reproduction/) | Original builders, existing emulation checks, and their input files |
| [`docs/technical-notes.md`](docs/technical-notes.md) | Patch addresses, diagnostics, provenance, and recovery notes |
| [`evidence/hardware-validation.json`](evidence/hardware-validation.json) | Sanitized record of the observed hardware results |
| [`SHA256SUMS`](SHA256SUMS) | Checksums for the repository's firmware and initialized RAM fixture |

The intermediate 06.06 binary is included only for reproducible construction and comparison. **06.08 is not included:** it was an uninstalled alternative candidate, and is not the firmware responsible for the confirmed result.

## Installation with the native Philips USB updater

This is the procedure used on the tested TV. Menu labels and available updater versions may differ. Read the compatibility and recovery limitations above before choosing to flash.

1. Check the remote's current firmware and exact model. The tested starting firmware was `GVK1EH_B002FFv.06.05`.
2. Copy the **`RCFW` directory inside `firmware/`** to the root of a USB drive. The resulting path must be `RCFW/GVK1EH_B002FFv.06.07.bin`. Preserve unrelated USB files.
3. Plug the drive into the TV. Open Philips' native **remote-control software update** screen from the TV's remote-control settings. Keep the remote within one metre of the TV and use good batteries. On this screen, press a rear keyboard letter once to wake Bluetooth before entering the USB sequence.
4. On the updater's initial screen, enter **1, 4, 5, 6, 3** with the **front infrared number keys**. Use short, separate taps, releasing each key fully. Long presses/repeats can reset the sequence. The updater must display **“Switched to USB drive successfully”** before proceeding. Bluetooth keyboard digits and generic ADB key injection did not select this mode in the tested updater.
5. Follow the native updater's connection prompts and check that it has selected the intended USB image. If you need to wake Bluetooth again, recheck that USB mode is still selected before starting.
6. Start the update once the intended USB image is selected and the Bluetooth connection is ready. Do not remove the batteries or interrupt the transfer. Wait for the native updater to report completion and for the remote to reconnect.
7. Reopen the remote information screen and verify **`GVK1EH_B002FFv.06.07`**. Close the updater and any temporary diagnostic clients.
8. Cover the infrared emitter and check the front arrows and rear keyboard. Then leave the remote untouched for 60 seconds and try one brief front arrow press in its normal position. Check standby/wake separately.

If the expected USB message or file selection does not appear, stop and investigate the updater version and input source. Do not substitute firmware from a different remote family.

## Reproduce and check offline

Requires Python 3 and the analysis-only packages pinned in [`requirements-analysis.txt`](requirements-analysis.txt). No TV connection is required. These commands rebuild files and emulate selected Thumb routines; **they never flash a device**.

```sh
python -m venv .venv
# Activate .venv using the command appropriate for your shell.
python -m pip install -r requirements-analysis.txt
python reproduction/emulate_initializers.py
python reproduction/build_front_hid_candidate.py
python reproduction/verify_front_hid_candidate.py
python reproduction/build_diagnostic_candidate.py
python reproduction/verify_diagnostic_candidate.py
```

The final generated file is `reproduction/candidates/diagnostic/GVK1EH_B002FFv.06.07.bin`; it must match the image in `firmware/RCFW/` byte for byte:

```text
35514fcd675876d4e016e23f389c58aab447db1bda1703adecef50834bda4a40
```

The front-HID suite contains **5 test methods**; the diagnostic-callback suite contains **6**. The first suite uses explicit stubs for external calls; the second executes the Device Information callback and its actual `strlen`/`memcpy`, without external-call stubs. Neither emulates the complete remote, its radio, peripherals, bootloader, or TV power management.

Build scripts intentionally label newly generated outputs as offline/unflashed. Those labels describe a build operation, not the installation history of the exact shipped binary. The separate hardware-validation record captures that history.

## What the firmware changes

- Replaces one voice-only branch at **`0x1D28`** (`05 D1`) with a Thumb NOP (`00 BF`), admitting ordinary front keys to an existing consumer-HID path. Existing readiness and bonding guards remain.
- Retains the rear keyboard and the separate front controller's UART command logic.
- Adds a bounded, read-only state formatter to the existing **Hardware Revision GATT characteristic (`0x2A27`)**, useful for diagnosing front-key/HID state. This diagnostic hook remains in the tested 06.07 binary. No separate diagnostic program is required during normal use.
- Changes the displayed software revision and recalculates the image's CRC16.

See [technical notes](docs/technical-notes.md) for offsets and validation boundaries. This is a binary patch and small assembly hook, not a complete firmware source reconstruction.

## Tools and attribution

[REA](https://github.com/morluto/rea) 6.7.0 was used to examine the Philips Android updater APK. [Ghidra](https://github.com/NationalSecurityAgency/ghidra) 12.1.4 was used directly for the raw Cortex-M firmware. REA was not used to execute the raw remote firmware. Capstone, Unicorn, and Keystone support the offline analysis and reconstruction.

This project is not affiliated with or endorsed by Philips, TP Vision, or the remote manufacturer. Firmware rights remain with their respective owners; no ownership of the original firmware or blanket open-source licence for it is claimed. See [third-party notices](THIRD_PARTY_NOTICES.md).
