# Research -> implementation -> verification

1. Implement bounded C core with host tests of event order/copy, transport acceptance, mixed report saturation/release repair, retries/TTL, epochs/CCCD, UART fragments and front key bounds. Compile the identical core for Cortex-M3 and execute it with Unicorn.
2. Integrate with verified 06.07 native ABI using per-hook expected bytes, native allocation/heap stats and critical tokens. Verify startup/failure fallback, producer callbacks, native dispatcher behavior, the HID task worker, allocation failures and unchanged OTA/audio/power regions with actual Thumb instructions. Integration cannot be declared qualified from core-only tests.
3. Implement and host-test gesture/profile logic, compile/sign the Android app using existing scoped SDK, inspect manifest and package. APK installation and service activation are separate material steps, not test substitutes.
4. Run positive and negative image-building checks, reproduce artifacts twice, review all assertions and map requirements to exact tests in status.md. Hardware requirements retain pending status until observed.
5. Prepare experimental diagnostic 06.09 and usage 06.10 artifacts only with explicit machine-readable qualification. No publish-as-validated, overwrite of baseline, automatic flash, automatic battery/radio changes or unproven recovery claim.

Owners work in separate paths: firmware/core, firmware builder/tests/CI, app, root native adapter/integration and delivery. Preserve existing user files and published 06.07.
