<h1 align="center">Philips SF463 · Bluetooth</h1>

<p align="center">Bluetooth navigation for the Philips double-sided remote.</p>

<p align="center">
  <img alt="Firmware 06.07" src="https://img.shields.io/badge/firmware-06.07-2563eb?style=flat-square">
  <img alt="Bluetooth HID" src="https://img.shields.io/badge/Bluetooth-HID-0082FC?style=flat-square">
  <img alt="Experimental" src="https://img.shields.io/badge/status-experimental-f59e0b?style=flat-square">
</p>

<p align="center">
  <a href="firmware/RCFW/GVK1EH_B002FFv.06.07.bin?raw=true"><strong>Download firmware</strong></a>
  · <a href="firmware/original/">Stock backup</a>
  · <a href="docs/technical-notes.md">Technical notes</a>
  · <a href="SHA256SUMS">Checksums</a>
</p>

---

### What it does

Enables front buttons to use the existing Bluetooth HID path, alongside the rear keyboard. **Front navigation, rear typing and TV wake were tested with infrared covered.** Infrared remains enabled; no companion app is needed.

| Remote | TV tested | Firmware |
| :--- | :--- | :--- |
| **YKF463-001 / SF463** | Philips **55OLED804/12** | Stock **06.05** → modified **06.07** |

### Install

1. Copy [`firmware/RCFW`](firmware/RCFW/) to the root of a USB drive and plug it into the TV.
2. Open the TV's **remote-control software update** screen. Keep the remote within one metre, with good batteries. Press a rear keyboard letter to wake Bluetooth.
3. Enter **1 → 4 → 5 → 6 → 3** using short taps on the **front infrared number keys**. Wait for **“Switched to USB drive successfully”**.
4. Check that the updater selects **06.07**, then start. Keep the batteries in place until completion and reconnection.
5. Verify version **`GVK1EH_B002FFv.06.07`**, close the updater, then test navigation with infrared covered.

> **Experimental, unofficial firmware.** Flashing can brick the remote; recovery is not guaranteed. Tested on one remote/TV combination. Other revisions and hours-long deep standby are unverified. Read the [compatibility and recovery notes](docs/technical-notes.md) before flashing.

### Build & verify

With Python 3 in a virtual environment, run the following offline. These commands **do not flash a device**.

```sh
python -m pip install -r requirements-analysis.txt
python reproduction/emulate_initializers.py
python reproduction/build_front_hid_candidate.py
python reproduction/verify_front_hid_candidate.py
python reproduction/build_diagnostic_candidate.py
python reproduction/verify_diagnostic_candidate.py
```

**11 emulation checks passed.** The rebuilt 06.07 matches the shipped binary. See [hardware validation](evidence/hardware-validation.json) and [patch details](docs/technical-notes.md).

### In development

The [reliability firmware and optional TV shortcuts app](docs/reliability-candidate.md) add bounded queues, release protection, reconnect handling and local button profiles. **06.07 remains the published reference.** The first 06.09 installed with inactive fallback; diagnostic 6.095 records the refusal cause. Hardware qualification remains pending, 06.10 is withheld, and no automatic flash is performed.

---

<sub>Not affiliated with Philips or TP Vision. Original firmware rights remain with their owners. <a href="THIRD_PARTY_NOTICES.md">Third-party notices</a>.</sub>
