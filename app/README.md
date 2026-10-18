# SF463 Companion · 0.1.0

Small native Android TV app for **optional remote-button shortcuts**. Android 8.0+; no runtime dependencies.

1. Open the app and review the disabled color-button preset: **Red → Movix · Green → HDMI 1 · Yellow → HDMI 2 · Blue → Companion settings**.
2. Learn buttons or edit their actions. Navigation, volume, power, Home, Back, voice and pairing remain available.
3. Manually enable **SF463 button shortcuts** in Android Accessibility, then enable your selected profile. Both switches are required.

Short presses run on release. Holds trigger once after **600 ms**. Double press is **off by default**; when configured, the second press must begin less than **300 ms** after the first release. Enabling double delays single actions by 300 ms. A second held press takes the hold action instead. Shortcuts pause while the companion is visible.

Profiles stay local. Import/export uses Android's document picker when available, otherwise an explicit JSON text/copy/paste dialog; imported profiles always start disabled. JSON `schemaVersion: 1` contains the active profile ID, profiles and button/action bindings. Reset restores the disabled preset.

Actions: installed TV application, Philips HDMI 1/2, Couchy, Android settings or companion settings. HDMI shortcuts use the verified Philips `HW5/HW6` input identifiers; other TV models may need different identifiers.

Each gesture's action editor offers **Test action** to open its current destination immediately, including while the profile is disabled. Testing does not enable the profile or change its bindings; Off cannot be tested.

**Privacy:** no Internet/Bluetooth permissions, screen-content access, advertising, analytics, GATT connection or background polling. The optional accessibility service filters configured key events only. Android starts that service according to the user's accessibility setting; no separate boot receiver or keep-alive is installed.

## Build and check

Python 3, JDK 21 and an existing Android SDK 34/build-tools 34 are sufficient. The builder downloads nothing.

```powershell
python app/build.py --test-only
python app/build.py --sdk-root C:/path/to/android-sdk --private-dir C:/private/sf463-signing --output-dir C:/builds/sf463
```

The local SDK may use standard SDK directories or extracted `build-tools-34.0.0/android-14` and `platforms-android-34/android-34` directories. Keep the generated signing identity and its password **outside Git** to preserve APK update compatibility.

Host tests cover profiles, strict JSON validation and gesture timing/ownership. TV rendering, document handling, accessibility delivery, destination launch and reboot behavior require separate device checks; see `.testagent/status.md` for the recorded scope. The app does not install or flash remote firmware.
