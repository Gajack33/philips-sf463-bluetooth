# Changelog

## 06.07 — 2026-10-18

First public release. Unofficial, experimental firmware for **Philips YKF463-001 / SF463**, based on stock **06.05**.

### Changes

- Enable ordinary front buttons through the existing Bluetooth consumer-HID path.
- Preserve the rear Bluetooth keyboard, pairing/readiness checks and infrared operation.
- Add a read-only diagnostic snapshot to the Hardware Revision characteristic (`0x2A27`). No companion app is required.
- Update the displayed revision to `GVK1EH_B002FFv.06.07` and recalculate the image CRC16.

### Validation

- Front navigation, rear keyboard and TV wake tested with infrared covered on one **55OLED804/12**.
- First front-arrow press worked after 60 seconds idle with diagnostic clients closed.
- 11 offline emulation checks passed; the rebuilt image matches the released binary.

### Limitations

Other hardware revisions, every physical key and hours-long deep standby are unverified. Flashing can brick the remote; the included stock image does not guarantee recovery.

See the [installation guide](README.md#install) and [technical notes](docs/technical-notes.md).
