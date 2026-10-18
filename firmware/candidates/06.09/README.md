# 06.09 · diagnostic candidate

[USB package](SF463-06.09-diagnostic-USB.zip) · [Binary](GVK1EH_B002FFv.06.09.bin) · [SHA-256](SHA256SUMS) · [Build manifest](manifest.json)

**Experimental; not flashed or hardware qualified. 06.07 remains the published reference.**

- Add separate 16-entry event/report queues and protected releases.
- Retry temporary failures, expire stale presses and cancel input across connections.
- Recover fragmented UART frames and compare full keyboard reports.
- Expose sampled heap/activity and the last front scan index through three diagnostic pages.

122 offline checks pass; two builds produced identical BIN/USB files. Native audio,
OTA, bootloader, radio settings and the 50% update-battery guard are preserved.
The physical Blue button still emits Yellow: its internal index needs confirmation.

Flashing can brick the remote; recovery is not guaranteed. Installation requires
explicit approval and the [hardware session](../../../docs/reliability-candidate.md#hardware-session--about-15-minutes).
Real heap/stack margin and first press/wake after 30 minutes and one night are pending.
06.10 remains compile-only until those checks pass. No automatic flash is included.

[Verification results](../../../evidence/reliability-offline.json) · [Full scope](../../../.testagent/status.md)
