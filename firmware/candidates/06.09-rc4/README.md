# 6.099 · reliability diagnostic (06.09 rc4)

**Experimental. Offline checks only; no hardware acceptance or automatic flash.**

- Snapshot each native queue slot before publishing its consumed index.
- Admit from APP without treating persistent HID readiness as a busy flag.
- Preserve held-button and rear-release order across the ownership handoff.
- Keep pending-report deduplication after initial neutralization and expiry.
- Preserve copied queues, the confirmed Blue mapping and native audio/OTA logic.

**178 checks pass with LLVM 18 and 19.** Two builds produce identical BIN/USB
files. Allocation stays at 640 bytes with a required 768-byte free reserve.
Real heap/stack, radio, voice and long-idle checks remain pending.

[USB package](SF463-6.099-diagnostic-USB.zip) · [Binary](GVK1EH_B002FFv.6.099.bin) · [SHA-256](SHA256SUMS) · [Changelog](CHANGELOG.md)

[Exact offline proof](../../../evidence/reliability-rc4-offline.json) · [LLVM 18 proof](../../../evidence/reliability-rc4-offline-llvm18.json)

[Contingency 6.100](recovery-6.100/) restores 06.07 code, version/CRC only.
It needs explicit approval and a working native update link; recovery is not
guaranteed. If installed, its numeric revision equals 06.10, so a later usage
build must be newer (for example 06.11). No usage image is delivered here.
Published 06.07 and the currently working 6.098 remain unchanged.
