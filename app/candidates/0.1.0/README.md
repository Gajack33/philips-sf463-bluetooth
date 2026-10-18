# Companion 0.1.0 · candidate

[APK](SF463-Companion-0.1.0.apk) · [SHA-256](SHA256SUMS) · [Usage and build](../../README.md)

Optional local button profiles, learning, short/hold/double gestures and JSON
import/export. No runtime dependencies, network permission or Bluetooth connection.

22 host tests pass. Installed on one Philips 55OLED804/12: UI, JSON round-trip,
user-enabled Accessibility and all six action destinations checked. The profile
remains disabled; physical shortcut delivery and long idle still need validation.
The Blue/Yellow duplicate in the remote prevents four independent color shortcuts
until its physical scan index is confirmed and the firmware mapping is corrected.

This app does not install remote firmware. [Device scope](../../.testagent/status.md).
