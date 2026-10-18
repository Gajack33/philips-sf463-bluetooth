# Test plan

1. ConfigTest: disabled preset; protected-key rejection; learned identity precedence; profile cloning/reset semantics; bounds and action validation.
2. GestureEngineTest: immediate short on release with double off; 600 ms long boundary; repeats; 300 ms optional double; canceled/disabled profile consumes owned UP; orphan UP and protected keys passthrough; independent buttons.
3. JsonCodecTest: multi-profile full-action roundtrip; schema/duplicate/protected/malformed rejection; import always disabled; size/depth boundaries; Unicode labels.
4. Builder static checks: manifest absence of INTERNET/Bluetooth permissions; accessibility no window retrieval; APK signature/min/target SDK.
5. Device checks explicitly pending: native UI appearance/focus, SAF picker, accessibility dispatch, app/HDMI launch, reboot behavior. No device install or enablement in this task.
