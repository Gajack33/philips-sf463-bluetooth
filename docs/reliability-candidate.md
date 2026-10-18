# Reliability firmware & TV shortcuts

**Experimental development builds. 06.07 remains the published reference.**
06.08 is not a build input. No command below installs or flashes firmware.

## Firmware

- Separate copied source events and pending HID reports, 16 entries each.
- One HID worker for keyboard and consumer reports. Failed notifications stay
  pending; full queues refuse presses and reserve neutral repairs for both faces.
- Press lifetime 2 seconds; temporary failures retry after 20/50/100/200 ms for
  at most 2 seconds, then wait for useful input/readiness. Accepted Power is never
  replayed. Peer, connection, protocol and notification changes cancel old input.
- Six-byte UART accumulator, FE resynchronization, native IRQ rearming after
  short/rejected reads, and fragment reset on native close/session timeout.
- Full eight-byte keyboard comparison. Front indexes 45–254 are rejected before
  the native lookup; release 255 and native special sequences remain supported.
- One native allocation of 640 bytes, with at least 768 bytes free afterwards.
  Failure keeps the working 06.07 input paths; diagnostic page zero reports inactive.

The original audio, OTA, bootloader, UART configuration, radio power and power
timings remain in place. The native 50% update-battery requirement is unchanged.
The Bluetooth test confirmed Blue emits Yellow. Its internal scan index is still
unknown, so the table is **not patched without that physical mapping**. Diagnostic
page two exposes the last valid front index for the next check.
Identity admission currently requires one saved bond and an exact current-address
match. Multiple bonds and rotating/private peer addresses are not qualified.

| Build | Purpose | Hardware status |
| --- | --- | --- |
| 06.09 first candidate | Temporary diagnostic pages through Hardware Revision (`0x2A27`) | Installed; adapter inactive, reason unknown |
| 6.095 (06.09 rc2) | Add frozen boot-refusal provenance in the same native buffer | Confirmed after host re-pair; inactive, initial bond count0 before allocation; on hold |
| 06.10 | Same reliability changes; original Hardware Revision callback restored | Withheld from usage qualification |

Read [native ABI notes](../firmware/NATIVE_ABI.md) for instruction windows and
the distinction between stack acceptance and delivery to Android.

[06.09 rc2 candidate files](../firmware/candidates/06.09-rc2/) include the BIN, USB archive,
SHA-256 and build manifest. Two builds produced identical BIN/ZIP files; all
134 offline checks pass with LLVM 18 and 19. [Machine-readable evidence](../evidence/reliability-rc2-offline.json)
binds the tests to exact source, hook and image hashes. 06.10 is compiled and
checked but no usage binary or archive is distributed before hardware acceptance.

The [first-candidate hardware result](../evidence/hardware-0609-rc1.json) confirms
06.09 was installed with inactive fallback. After initial Bluetooth failures, a
separately authorized host forget/re-pair restored PHLRC input and six successful
ATT reads. The [6.095 hardware result](../evidence/hardware-6095.json) confirms its
revision and inactive core: initial bond count0, before allocation. This does not
establish why inventory was zero or qualify the heap reserve. The rc2 follow-up
preserves the exact boot refusal code, bond count, heap sample and native readiness
flags in the existing 21-byte diagnostic buffer. Reads do not retry initialization
or query BLE/NVRAM/heap. Unknown heap values are explicit; post-allocation samples
are distinguished from pre-allocation samples. The device revision is 6.095,
strictly between 06.09 and 06.10 under the updater's native float comparison.
This preserves the original 20-byte revision field and the planned usage 06.10.

The separately authorized [6.096 recovery](../evidence/hardware-recovery-6096.json)
restored the published 06.07 code; only revision and CRC differ. The native transfer
completed and an independent six-read ATT sequence confirmed version 6.096. Its
15 narrow offline checks do not qualify the reliability changes. The owner reports
both faces and first press after an unmeasured pause work with infrared covered;
long idle remains unqualified. No new normal-use release is published.

## TV companion

[SF463 Companion](../app/README.md) is optional and independent of firmware.
It offers button learning, local profiles, short/600 ms hold/optional 300 ms
double actions, versioned JSON import/export and reset. No networking, screen
content access, Bluetooth connection or runtime library is needed.

The [0.1.0 APK](../app/candidates/0.1.0/) is installed on the test TV. UI, JSON
round-trip and all six action destinations were checked through the app's
explicit Test action controls; the shortcut profile remains disabled.

The disabled preset is Red → Movix, Green → HDMI 1, Yellow → HDMI 2,
Blue → companion settings. The user must manually activate Android Accessibility
and choose an enabled profile. Ordinary navigation, volume, Power, voice and
pairing are preserved. Duplicate physical color codes must be resolved before
claiming four independent shortcuts.

## Reproduce

Use Python 3, the pinned analysis packages, a Cortex-M3-capable Clang/LLD or
Zig CC, GCC (WSL on Windows) for host sanitizers, and JDK 21 for app logic tests.
The APK additionally needs an existing Android SDK 34/build-tools 34.

```sh
python firmware/verify.py --compiler /path/to/zig --out /path/to/verification
python firmware/build.py --compiler /path/to/zig --variant diagnostic --check --out /path/to/diagnostic
python firmware/build.py --compiler /path/to/zig --variant usage --check --out /path/to/usage
```

Export without `--check` requires matching offline integration evidence: sources,
hook manifest and exact compiled image. A different compiler output needs fresh
qualification. The builder checks stock and 06.07 hashes, expected instructions,
modified ranges, image length, vectors, metadata and CRC. USB archives have fixed
metadata and contain only `RCFW/<version>.bin`.

Artifacts use Zig 0.14.1 / LLVM 19.1.7. Compiler and analysis dependencies are
build tools, not additions to the TV or remote. See [.testagent/status.md](../.testagent/status.md)
for exact checks, evidence and outstanding requirements.

## Hardware session — about 15 minutes

1. Record versions, pairing, battery and the 06.07 behavior. Firmware installation
   requires a separate explicit approval; keep the sole remote powered throughout.
2. On 06.09, read diagnostic pages briefly; confirm the adapter is active and
   sampled free heap remains at least 768 bytes during keyboard, voice and update
   screen checks. No deliberate flash interruption or forced low-battery test.
3. Cover infrared. Try every front button and rear typing, alternate faces, tap
   rapidly, hold/release arrows and volume, and check no key remains held.
4. Learn the four physical colors. Confirm codes and actions independently;
   enable a profile only by choosing it in the companion. Check HDMI 1/2,
   Movix, Couchy, settings, long/double actions, JSON round-trip and reset.
5. Check standby/wake, the first press after 30 minutes, then after one night.
   Close diagnostic clients before idle tests. Keep dates and observations.
6. Qualify 06.10 for normal use only after those checks pass. Restore the original
   Hardware Revision value and repeat first-press/wake checks without diagnostics.

The decoder accepts complete pages with the exact installed version (06.09 or 6.095):

```sh
python firmware/decode_diagnostic.py --firmware-version 6.095 PAGE0 PAGE1 PAGE2
```

Heap values are sampled minima; connection and logical UART active/inactive
durations are software activity indicators. Separate page reads are not atomic.
The native 32-bit 10 µs clock wraps in about 11.9 hours: intervals longer than one
unobserved wrap cannot be reconstructed exactly. No measured battery-life gain
or recovery by programmer is claimed. Energy changes remain gated on measurements.
