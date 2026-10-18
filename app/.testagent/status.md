# Completed host checks; focused device checks completed

## Device session, 2026-10-18

The signed app was subsequently installed on the verified Philips 55OLED804/12 (Android 12). Cold launch completed successfully; real screenshots and UI hierarchy inspection confirmed D-pad focus, binding editor and action selector. Both the default profile and accessibility service were disabled at initial observation. Accessibility activation remains a user action.

The TV advertises OPEN_DOCUMENT/CREATE_DOCUMENT via `com.android.tv.frameworkpackagestubs/.Stubs$DocumentsStub`, not a usable document provider. MainActivity now offers explicit JSON text/copy/paste in that case, with clipboard read/write only on the user's corresponding button. Rebuild: 22 host-Java tests and all APK checks pass. Updated APK: 37,405 bytes, SHA-256 `096b5033ac64dc4efa28b8dc085f8bd35c28dbe98a8d49041dd74f5f077de89e`; installed successfully. On-device JSON export, explicit copy/paste, and import all succeeded; the imported default profile remains disabled. The user subsequently enabled Accessibility and Android reports the service bound with key-filter capability, no subscribed events, and no crashed service. Actual shortcut dispatch remains untested because the profile has not been enabled by the user.

Private device evidence is outside Git under `outputs/SF463-implementation/device/companion/`. No firmware flash was performed. Couchy automatically added the new app. Its scoped Hide command removed only the companion tile; a final screenshot and hierarchy confirm the dock contains exactly Movix, HDMI 1, and HDMI 2.

Clean final APK build exited 0: **22 host-Java tests passed**; manifest privacy assertion passed; APK signature verified; minSdk 26 / targetSdk 34 verified with aapt2. No external production dependency, package download, agent-driven service/profile enablement, Git commit or publish was performed. The signed APK was installed and updated during the later authorized device session.

The specialist test-gap-analysis/assertion-quality tools are unavailable. Inline review checked meaningful expected actions and secondary state (owned UP, deadlines, no repeats, no unexpected short actions, disabled import/reset), plus rejection tests that preserve the original configuration. The review found and fixed: a canceled UP could dispatch a delayed hold; a fresh DOWN after a missing release could reuse stale hold state; numeric Unicode escapes needed strict hexadecimal validation. Regression cases cover all three.

| Requirement | Evidence |
|---|---|
| “learning buttons” | `testLearnedIdentityOverridesWildcardWithoutMatchingOtherDevice`; learning view renders on the TV; actual learned Android key/scan/vendor/product IDs remain unvalidated. |
| “versioned JSON import/export/reset” | `testJsonRoundTripAllActionsMultipleProfilesUnicode`, `testJsonRejectsUnknownSchemaDuplicateKeysAndProtectedImports`, `testJsonRejectsMalformedAndOversizeWithoutChangingExistingConfig`, `testDisabledColorPresetAndReset`; the actual TV document stub is bypassed by the explicit JSON text/copy/paste dialog; roundtrip passed on the TV. |
| “local profiles” | `testProfileCloneIsDisabledAndBindingsIndependent`, `testJsonRejectsDuplicateButtonsAndUnknownActiveProfile`; Store.java uses app-private SharedPreferences. |
| “actions app/HDMI1/2/Couchy/settings/selfsettings” | `testJsonRoundTripAllActionsMultipleProfilesUnicode` validates model serialization; Actions.java implements actual intents. An explicit native Test action button launched all six action types on the verified TV: Movix, HDMI 1, HDMI 2, Couchy, Android settings and Companion settings. Foreground activities/window focus were checked. HDMI video/physical-port selection was not visually validated: screencap returned no pixels on both HDMI surfaces. |
| “Preset redMovix greenHDMI1 yellowHDMI2 blueSelf DISABLED until selected” | `testDisabledColorPresetAndReset`. |
| “Short/long600ms/double300ms doubleoff” | `testShortOnReleaseNoDelayWithDoubleOffAndRepeats`, `testLongExactlyAt600AndNoShortOrRepeatAction`, `testLongReleaseBoundaryWorksWhenTimerIsLate`, `testDoubleWindowAndSingleDeadline`, `testSecondDownAtDeadlineStartsNewSingle`, `testLongWinsOverDoubleAndDoesNotEmitShort`. |
| “protected DPAD/volume/power/home/back/voice/pair defaults passthrough” | `testProtectedKeysNeverBindOrIntercept` covers all protected codes with short/hold/double enabled on the active profile. |
| “coherent down/up interception” | `testProfileChangeCancelsActionButConsumesOwnedRelease`, `testCanceledReleaseAndOrphanEventsPassthrough`, `testFreshDownRecoversMissingReleaseWithoutStaleHold`, `testTwoDevicesAndButtonsKeepIndependentOwnership`, `testCompanionForegroundDoesNotCapture`. |
| “Accessibility service only key filtering, no window content/network/GATT/background polling” | AndroidManifest.xml requests no application permissions; key_service.xml disables content retrieval and subscribes to no events; RemoteKeyService.onServiceConnected explicitly sets eventTypes=0. Builder asserts these shipped metadata invariants. Main-thread Handler runs only for pending gesture deadlines; no periodic tasks. |
| “Build signing material new under workspace work/app-build-private (not repo), no keysinGit” | build.py rejects private paths inside the repository; generated identity stored outside Git; app/.gitignore excludes keys/build outputs. APK cryptographic verification passed. |

Important semantics: optional double uses a second DOWN strictly before the first release + 300 ms; at the deadline the first single action is emitted. A held second press emits only its hold action. Profile changes cancel pending actions while retaining ownership of already consumed DOWN/UP sequences.

Verified on device: native rendering and D-pad focus, binding editor/action selector rendering, explicit JSON export/copy/paste/import, user-enabled service binding, disabled-profile preservation, and the original three-item Couchy dock. Pending: actual key learning and Android identity mapping, shortcut delivery with an explicitly enabled profile, end-to-end shortcut-triggered launches, physical HDMI signal/port confirmation, and idle/standby/reboot behavior. The built APK remains a partially device-validated candidate.

A bounded passive color-input capture after rear-keyboard Space reported front Bluetooth RED, GREEN, YELLOW, YELLOW for the user-confirmed physical Red, Green, Yellow, Blue sequence. Before rear Space, Bluetooth was disconnected and the remote input device absent; afterwards it was connected and present. The first three presses also appeared on the IR-associated input path, so complete IR suppression is not established. The color capture used no GATT reader. A later separate one-read 2A27 diagnostic attempt closed its GATT client after the 20-second deadline without connecting or obtaining a value; no raw front UART index was confirmed. No firmware flash was performed.

## Explicit action-button device checks

Each short/hold/double editor now offers **Test action** for its current saved action. It is disabled for Off and does not enable the profile. The updated APK was rebuilt and reinstalled with the existing private signing identity: **22 host tests passed**, manifest privacy checks passed, signature verified; 37,405 bytes, SHA-256 `096b5033ac64dc4efa28b8dc085f8bd35c28dbe98a8d49041dd74f5f077de89e`. No new production dependency or permission was added.

| Requirement | Observed device evidence |
|---|---|
| Explicit Test action without enabling a profile | Native editor button focus inspected; each launch followed its focused button click. Profile remained disabled. |
| Movix | Foreground/focus `com.movix.tv/.MainActivity`; screenshot inspected. |
| HDMI 1 and HDMI 2 | Foreground/focus `org.droidtv.playtv/.PlayTvActivity` after each respective action. The intent code uses HW5/HW6; no HDMI pixels were returned by screencap, so physical signal/port selection remains unverified. |
| Couchy | Foreground/focus `com.conreo.couchytv/.MainActivity`; screenshot inspected, exactly Movix/HDMI 1/HDMI 2 tiles. |
| Android settings | Foreground/focus `org.droidtv.settings/.setupmenu.SetupMenuActivity`. |
| Companion settings | Foreground/focus `fr.local.tv.sf463/.MainActivity`. |
| Existing accessibility authorization | Secure setting preserved; Android rebound the service after APK replacement, capability 8, no subscribed events or crashed service. No agent activation. |

The temporary Blue-action changes for Couchy/Settings validation are restored to Companion settings before closing the session. Detailed screenshots/UI hierarchies and actual activity/focus records are kept privately under `outputs/SF463-implementation/device/companion/test-*-result.json`.

Final state was verified through a fresh UI JSON export, structurally identical to the original disabled preset. Accessibility remained bound under the owner's existing authorization. The session ended on Couchy with exactly Movix, HDMI 1 and HDMI 2. The installed APK was independently hashed on the TV and matches the local APK. Sanitized device evidence is recorded in `evidence/companion-device.json`; no firmware was flashed during this app task.
