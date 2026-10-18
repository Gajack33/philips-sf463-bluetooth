# Changelog

## 6.099 (06.09 rc4) — offline diagnostic candidate

- Copy native queue slots before publishing their consumed index.
- Preserve held-button and source-release order during ownership handoff.
- Preserve pending-report deduplication after initial neutrals and expiry.
- Add versioned refusal 12 for unresolved rear source state.
- Hardware acceptance is pending. Optional recovery 6.100 restores 06.07 code; if installed, it consumes the numeric 06.10 revision.

## 06.10 — development, not hardware qualified

- Keep the reliability changes from the 06.09 candidate.
- Restore the original Hardware Revision characteristic and remove diagnostic code.
- Normal-use qualification remains pending the 06.09 hardware and idle checks.

## 6.095 (06.09 rc2) — activation diagnostic follow-up

- Record the boot refusal reason and available memory in the existing diagnostic buffer.
- Preserve the refusal snapshot across reads; keep allocation and safety guards unchanged.
- Use intermediate revision 6.095 for the native updater; planned usage 06.10 stays newer. Hardware validation is pending.

## 06.09 — first diagnostic candidate, installed with inactive fallback

- Add copied event/report queues, protected releases and bounded retry/expiry.
- Purge stale input across pairing/reconnect and preserve native forced erase ordering.
- Recover fragmented UART input and compare complete keyboard reports.
- Add sampled heap/activity counters and the last front scan index; preserve native audio, OTA and power settings.
- Installation confirmed on one remote; the reliability adapter reports inactive and needs refusal diagnostics.

## Companion 0.1.0 — Android TV

- Add optional local button profiles, learning and app/HDMI/settings actions.
- Support short, hold and optional double press; import/export versioned JSON.
- Keep Accessibility and shortcut profiles under explicit user control.

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
