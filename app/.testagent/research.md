# Scope and acceptance

New, isolated native Java Android TV companion; no pre-existing app tests or app source.
The test-generator/find-untested-sources/test-gap-analysis/assertion-quality tools are unavailable; the Research → Plan → Implement workflow runs inline.

- Learn non-protected button identities; local profiles and explicit enable/disable.
- Versioned JSON import/export/reset, rejecting invalid actions, duplicate buttons and unsupported schemas.
- Short/long 600 ms/double 300 ms; double off by default; coherent DOWN/UP handling and repeats.
- Protected navigation, volume, power, home, back, voice and pairing remain passthrough.
- Default red Movix, green HDMI 1, yellow HDMI 2, blue companion settings; disabled.
- Actions: selected app, Philips HDMI 1/2, Couchy, Android settings, companion settings.
- Accessibility key filter only; no window content, network, GATT, or polling.
- Native Java build with existing SDK 34/min 26, no production dependency; signing outside repository.

Inventory: core/Config.java, core/JsonCodec.java, core/GestureEngine.java are host-Java-testable. Android adapters (Store, RemoteKeyService, Actions, MainActivity) require actual TV or emulator for lifecycle and UI validation; host checks must not be represented as device validation.
