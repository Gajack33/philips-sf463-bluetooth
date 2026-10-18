# Technical notes

## Baseline and provenance

The original image is `GVK1EH_B002FFv.06.05.bin`, exactly 118,784 bytes:

```text
SHA-256: 6b97d87fd4923eb64a0e5f5efad1561900ed394ff3a7db97b3081cf5e316f040
MD5:     8eb7ab352f4d990069fa9301919c0539
```

It was extracted from the `ro/BTRC_FW` directory in the USRS partition of a publicly shared Philips TV recovery package, `EU_PKG_TPM191E_211.000.092.200.zip`:

```text
Archive SHA-256:
4b7320d38d3d47e4b07f79461f21b09419fe7b9b0b854ce7fc81431616550022
```

The archive was located through [this Philips recovery discussion](https://www.reddit.com/r/Philips/comments/1lvhnot/philips_tv_not_working/). Its bundled MD5 entry and the remote image's internal CRC were checked. These consistency checks do not authenticate a third-party archive as an official Philips distribution. The repository does not include the multi-gigabyte TV recovery image.

The images are not device-specific dumps and contain no captured pairing database. No TV/NAS credentials, private keys, addresses, or full conversation transcript are included.

## Front-key patch

The remote's front side has a separate controller communicating with the Bluetooth MCU over UART. The Bluetooth firmware already contains a consumer-HID mapping for front keys. Analysis found a voice-only gate in the dispatch path.

| Offset | Factory | Patched | Purpose |
| --- | --- | --- | --- |
| `0x1D28` | `05 D1` | `00 BF` | Replace `BNE 0x1D36` with Thumb NOP |
| `0x16E0` | `GVK1EH_B002FFv.06.05` | `GVK1EH_B002FFv.06.07` | Local displayed revision |
| `0x52B2` | `02 F0 F7 F8` | `11 F0 A5 FE` | Redirect the relevant `strlen` call through the diagnostic formatter |
| `0x17000` | Erased `FF` bytes | 302-byte Thumb stub | Format existing state for Hardware Revision reads |
| `0x0000` | Original CRC16 | Recomputed CRC16 | `binascii.crc_hqx(image[4:], 0)`, stored little-endian |

Build 06.06 contains only the front-key gate, revision, and CRC changes. Build 06.07 is constructed from that exact intermediate image and adds the state formatter. Readiness and bonding checks remain; the change does not force a permanent Bluetooth connection or disable infrared transmission.

The native updater checks file-name versions. Changing a file name is not evidence of bypassing bootloader security. No bootloader or pairing-data modification was performed.

## Diagnostic characteristic

For Hardware Revision `0x2A27` only, the hook formats existing state into the existing 21-byte RAM buffer at `0x20000664`: 20 uppercase hexadecimal characters plus a terminator. Other Device Information reads preserve the original callback path.

The 10 bytes are:

1. Role state.
2. Application HID-ready state.
3. UART-active state.
4. UART-face state.
5. Last front usage, low byte.
6. Last front usage, high byte.
7. Last consumer usage, low byte.
8. Last consumer usage, high byte.
9. First consumer CCCD slot value (`FF`: unavailable; `FE`: belongs to another connection).
10. Last front-key index.

The formatter checks pointer alignment and RAM bounds, preserves callee-saved registers and stack, and adds no peripheral, ROM, GAP, GATT, or UART command calls. Its assembly is embedded in `reproduction/build_diagnostic_candidate.py`.

Examples observed during the test:

```text
06050100450045000124  Right front usage and consumer usage 0x0045
060501004500000001FF  Right release
06050100440044000118  Left front usage and consumer usage 0x0044
060501004400000001FF  Left release
```

The diagnostic reader was subsequently stopped. The final 60-second-idle test succeeded without it.

## Hardware evidence and limitations

On this TV, consumer Bluetooth arrows appeared through the vendor's virtual `TPV_SMTRC` input device, while actual infrared appeared through `TPV_MutilRC`. Merely looking for front arrows on the raw `PHLRC` keyboard device would miss the consumer-input path. Input event numbers are TV-specific and are not part of this project's installation requirements.

The final result combines internal usage snapshots, front-arrow press/release captures without matching IR, the owner's covered-IR tests of both faces and TV wake, and the independent first-press test after 60 seconds. The original orientation-dependent symptom alone does not prove a failed orientation sensor, and the precise hardware cause was not conclusively identified.

The repository's emulation checks cover selected code paths. They do not prove MCU boot, BLE radio behavior, UART electrical behavior, OTA recovery, all key mappings, absence of duplicate IR/Bluetooth actions, or long deep-standby wake. 06.06 alone was not accepted as a working hardware result; the reported successful installation is 06.07. No claim is made that the diagnostic hook itself causes the improvement.

## Recovery notes

The original 06.05 bytes are preserved in `firmware/original/`. On the tested updater, a separate USB directory named `RCFW_DOWNGRADE` can be selected with infrared digit **8 after entering USB mode**. Its file-name version filter may require a name higher than the installed build. During preparation, copies of the original bytes were renamed to higher versions for this filter; this did not alter their embedded version or make them a new Philips build.

No misleadingly renamed recovery images are shipped in this repository. If preparing such a copy, compare its SHA-256 with the original before use. A successful installation would still report embedded version 06.05. This is an observed updater selection mechanism, **not a tested recovery procedure**. It cannot recover a remote whose bootloader or Bluetooth connection no longer works.
