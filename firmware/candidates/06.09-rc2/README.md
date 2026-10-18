# 6.095 · activation diagnostics (06.09 rc2)

**On hold — do not install while the hardware failure is investigated.** After
the transfer, the owner reports that the rear Bluetooth keyboard is unavailable;
the TV has no PHLRC input device. Battery reset, normal pairing and a TV Bluetooth
restart have not restored it. The actual installed revision remains unreadable.

[USB package](SF463-6.095-diagnostic-USB.zip) · [Binary](GVK1EH_B002FFv.6.095.bin) · [SHA-256](SHA256SUMS) · [Build manifest](manifest.json)

Diagnostic follow-up to the first 06.09, which installs but reports inactive
fallback on the test remote. It records the boot refusal reason, bond count,
free/largest-block memory and native readiness flags in the existing Hardware
Revision buffer. Inactive reads preserve that snapshot.

**No forced activation, allocation retry, lower safety threshold or new state
allocation.** The 640-byte cap and 768-byte free reserve remain in place.
The device revision is `6.095`: the native updater requires a strictly greater
numeric revision, and `6.09 < 6.095 < 6.10`. The five-character revision keeps
the original 20-byte Software Revision field and permits the planned 06.10 later.

134 offline checks pass with LLVM 18 and 19. Two builds produced identical BIN/USB
files; the [proof](../../../evidence/reliability-rc2-offline.json) binds exact source,
hook and image hashes. Each refusal is tested through compiled C, GATT reads and
the decoder.

The [authorized USB transfer completed](../../../evidence/hardware-6095.json), but
Bluetooth read failures prevent confirmation of the installed revision and adapter
state. Hardware validation is pending. Flashing is experimental and can brick the remote;
recovery is not guaranteed. No automatic flash is included. 06.07 remains the
published reference, and 06.10 remains withheld from usage qualification.

[First-candidate hardware result](../../../evidence/hardware-0609-rc1.json) · [Validation scope](../../../.testagent/status.md)
