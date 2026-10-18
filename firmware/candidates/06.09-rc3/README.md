# 6.097 · reliability diagnostic (06.09 rc3)

**Experimental. Hardware acceptance pending. No automatic flash.**

- Retry guarded initialization after useful connection/pairing transitions.
- Preserve native reports still in flight when claiming the old queue.
- Give the confirmed physical Blue button its own Bluetooth usage.
- Report the latest boot/deferred refusal without permanent diagnostics.

**155 checks pass with LLVM 18 and 19.** Two builds produce identical BIN/USB
files. The single 640-byte allocation, 768-byte reserve, original audio/OTA/
bootloader and battery guards remain. Real heap/stack and long idle are unqualified.

[USB package](SF463-6.097-diagnostic-USB.zip) · [Binary](GVK1EH_B002FFv.6.097.bin) · [SHA-256](SHA256SUMS) · [Changelog](CHANGELOG.md)

[Exact offline proof](../../../evidence/reliability-rc3-offline.json) · [LLVM 18 proof](../../../evidence/reliability-rc3-offline-llvm18.json) · [Color observation](../../../evidence/hardware-colors-6096.json)

[Contingency 6.098](recovery-6.098/) restores 06.07 code, version/CRC only. It
needs separate or explicitly conditional owner approval and a working Bluetooth
update link. Flashing can brick the remote; programmer recovery is not established.
Published 06.07 remains the reference. 06.10 stays withheld.
