# Native ownership handoff — diagnostic 6.099

The [rc4 candidate](../firmware/candidates/06.09-rc4/) is checked offline against the exact [LLVM 19](../evidence/reliability-rc4-offline.json) and [LLVM 18](../evidence/reliability-rc4-offline-llvm18.json) proofs. It has not been installed or hardware qualified. Published 06.07 and the working 6.098 remain unchanged.

## History and current baseline

- Historical diagnostic **6.097** could remain inactive on an ordinary connection. Its admission guard treated persistent HID readiness `HID+0x0E` as transmission quiescence. Native code sets readiness at `0x4D12`; completing the last legacy report does not clear it. The captured inactive record was refusal 11. This establishes the refusal, not the cause of the owner's delayed input. Keep its image, proofs and versioned decoder contract unchanged.
- Restored **6.098** is the published 06.07 implementation with only its Software Revision and CRC changed. `evidence/hardware-recovery-6098.json` records native/independent revision confirmation and the owner's report that both faces work again. It does not qualify long-idle behavior or the reliability candidate. The duplicate original color mapping remains part of that baseline.
- **6.099** is the next offline diagnostic candidate. It carries forward the existing reliability work and reviewed one-byte Blue usage correction; neither has new hardware acceptance.

## Changes in 6.099

1. **Make the old reader independent of reclaimed queue memory.** The hook replacing `BL 0x5006` at `0x4784` copies the entire next 12-byte legacy slot to a 16-byte HID stack frame under the native gate, then publishes the consumed index. Native `0x4EF4` receives the private copy after the gate is released. If APP claims the queue while that native call waits in RPC, its return skips to `0x47AA`, before legacy index reads or reposting. An invalid length above nine bytes is not transmitted.
2. **Keep admission in APP and remove the persistent-readiness exclusion.** APP remains the owner of both native queue production and allocation/claim. Original initialization `0x13E4` runs once. Filtered lifecycle events schedule admission through APP Event `0x400`; they do not allocate from HID. The 640-byte single allocation, identity checks, pre-allocation free/largest-block checks, 768-byte post-allocation reserve and final mailbox/queue guards remain in force. Native transmission still requires readiness; admission no longer mistakes that flag for an in-flight indicator.
3. **Distinguish inherited attempts from fresh input.** The handoff flag occupies the existing tail-padding byte at offset 639, without enlarging the allocation. At claim, a held front usage matching the native Consumer last-attempt value is fenced until its physical release. This is attempted-state deduplication, not proof of notification acceptance or host delivery. Synthetic initial neutrals and orientation reports do not prove release. The reference cases include release-generated `0x41` and pending voice `0x221`, so a legitimate action not yet attempted is preserved rather than suppressed as an old Power hold.
4. **Do not infer rear release from a stale native sentinel.** Native `1FDA` checks UART readiness before decoding release; an unready release can leave `APP+1B` and the keyboard attempt cache unchanged. Admission therefore refuses unresolved rear source state with diagnostic reason **12, `rear_source_unresolved`**. Only the actual rear source call at `0x188C`, after the complete native decoder and with an unambiguous physical release, supplies local release proof. A successful claim can clear the stale rear held/pending sentinels; a refusal preserves native fallback state. No keyboard report cache or modifier state is fabricated.
5. **Preserve ordering across overflow and initial repairs.** A release refused by a source-overflow barrier may lift the handoff fence only after the older FIFO is purged. A suspended stale dispatch remains fenced. After an accepted initial neutral or TTL expiry, deduplication is rebuilt from the newest remaining valid admitted frame for that report ID; it is never copied into accepted state merely because it was queued.

## Diagnostic compatibility

The embedded revision is exactly `GVK1EH_B002FFv.6.099` (20 ASCII bytes). The page decoder must use the captured embedded version, not a chosen filename.

Reason 12 is valid only for 6.099. Its early refusal has unknown bond count `FF` and heap values `FFFF`; its final refusal has one bond and a post-allocation sample with at least 768 free bytes. Largest block must not exceed total free. Flag `0x10` retains the latest deferred-admission scope introduced in 6.097. Historical reason 11 remains valid only for 6.097; older 06.09/6.095 schemas stay strict. Reads do not query heap/NV, retry admission or refresh the frozen refusal record. The usage variant retains the original Hardware Revision behavior.

## Contracts and limits to retain

- The pinned factory image, hook-byte allowlist and native function contracts are build-specific. APP is the only legacy producer/admission owner; HID is the reader and sole active HID transmitter. BLE/IRQ callbacks enqueue work instead of transmitting through a second owner.
- The same native gate protects the bounded copy and final claim. No heap, BLE, NV query or other blocking API runs while that gate is held. Native `0x4EF4` may finish after claim, but it must retain only its stack copy and skip all reclaimed legacy postlude.
- The private 16-byte shadow is an added retained HID stack cost. Existing 400-byte HID and 750-byte APP budgets are not increased. Emulator stack prefixes and explicit API seams do not prove ROM, interrupt or scheduler worst cases.
- Source callbacks must preserve native ordering, rear/front provenance and epoch checks. A real key-up is distinct from a neutral HID report. Native attempt caches must never seed `accepted[]` or claim delivery.
- Unknown peer identity, multiple bonds, insufficient memory and invalid protocol/subscription state remain fail-closed. Notification acceptance is not an end-to-end delivery acknowledgment.

## Remaining qualification

The source commit, source/hook hashes and exact compiled images are bound in the linked proofs. See the [linked stack review](../evidence/stack-review-6099.json) for the actual measured prefixes and limitations. Passing software checks does not establish radio behavior or physical memory headroom.

Before any separately authorized device trial, prepare a reviewable exact candidate and recovery plan. A hardware trial must establish actual active diagnostic pages and identity/headroom, not merely a successful transfer or Software Revision read. Check both faces with IR blocked, a held Power across activation, release/fresh press, release-only `0x41`, pending voice, orientation, reconnect/CCCD/protocol changes and a measured idle interval. Qualify stack headroom, ATT responsiveness and battery behavior separately. Do not attribute the earlier delay to admission solely from its refusal snapshot.

## Recovery 6.100 and the usage-version boundary

The [6.100 contingency](../firmware/candidates/06.09-rc4/recovery-6.100/) is an offline recovery package based on published 06.07, changing only the revision and original CRC. The actual three Philips Java comparators establish:

`6.099 < 6.100 == 06.10 < 06.11`

Equality is rejected by native selection. **Installing recovery 6.100 would consume the numeric version reserved for usage 06.10.** An unchanged 06.10 package, and diagnostic 6.099, could not then replace it through the normal strict-greater updater. A later usage revision would need a newly chosen higher numeric value and its own exact-header/comparator checks. No higher usage revision is selected here, and recovery installation is not authorized. Historical recovery artifacts and candidate proofs remain immutable.
