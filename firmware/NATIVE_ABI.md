# Native ABI evidence

Addresses below apply only to `GVK1EH_B002FFv.06.05.bin`, 118,784 bytes,
SHA-256 `6b97d87fd4923eb64a0e5f5efad1561900ed394ff3a7db97b3081cf5e316f040`.
The published 06.07 is a separate, immutable comparison input. `hooks.json`
contains the complete expected-byte allowlist; `adapter.S` reconstructs replaced
instructions and their PC-relative literals rather than relocating raw bytes.

## Entry and callback boundaries

| Entry | Original bytes | Required continuation / contract |
|---|---|---|
| `0x1878` APP drain | `feb5dff80c47` | Recreate its 32-byte saved frame and APP pointer; native non-source processing resumes at `0x189E`. |
| `0x1A90` rear callback | `ff280246` | Recreate `CMP r0,#255` and `MOV r2,r0`, including flags; resume `0x1A94`. |
| `0x1ABC` front callback | `38b5dff8f84a` | Recreate `push {r3,r4,r5,lr}`, load APP; resume `0x1AC2`. |
| `0x48F4` control | `2de9f843` | Recreate `push {r3,r4,r5,r6,r7,r8,r9,lr}`; inactive path resumes `0x48F8`. |
| `0x5250` Device Information | `2de9ff4d` | Six arguments; original 48-byte saved frame keeps offset/max length at SP+48/SP+52. The output length is `uint16_t *`. |
| `0x53A2` UART close | `10b5dff87843` | Six-byte hook needs branch + `00bf`; recreate `push {r4,lr}`, load UART; resume `0x53A8`. |
| `0x551A` UART receive | `bcb5804c` | Recreate its 24-byte saved frame, load UART; resume `0x551E`. A supplied complete frame resumes `0x552C`. |
| `0x5648` UART worker | `f8b5354c` | Recreate `push {r3,r4,r5,r6,r7,lr}`, load UART; resume `0x564C`. |

Native UART parsing returns to `0x555A` after orientation, `0x5568` after a
key callback and `0x5608` after an FB orientation message. Mask the Thumb bit
before comparing return addresses. These callbacks must run before later queued
rear inputs; re-enqueueing them at the tail changes physical event order.
The IRQ callback returns at `0x5702` and must only post APP work.

`UART[7]` gates IRQ posting at `0x56EC..0x5704`: original short/invalid reads
clear it at `0x561C`/`0x5612`. Retaining partial bytes alone is insufficient.
`0x55DE` and timeout tail `0x56B6` reach UART close; the timeout path
`0x56B8..0x56DA` ends a logical session without calling close.

## HID transmission and control

Direct call sites in the decoded application:

| Target | Call sites |
|---|---|
| `0x488E` report submission | `0x21C6` keyboard, `0x2204` consumer |
| `0x4FAA` legacy enqueue | `0x48D8` |
| `0x4EF4` legacy send wrapper | `0x479A` drain, `0x48BC` fast path |
| `0x4F58` allocation/notification | `0x4944` control neutral, `0x4F36` legacy wrapper |
| `0x48F4` control | `0x225A`, `0x2266`, both through `0x2248` |

No aligned references to these Thumb function pointers were found in the pinned
image or initialized RAM context. This is a bounded static inventory, not proof
against every possible computed branch. Battery, service-change, ATT and OTA
notifications use other paths; the single-worker property concerns HID IDs 1/2.

`0x4F58(handle,length,data)` returns zero when the stack accepts the notification;
null allocation returns `0x13`, and a refused stack request frees its allocated
buffer. Acceptance is not a host-delivery ACK. `0x4EF4` discards this status.
Its native `0x319` one-shot parameter request precedes allocation; preserve that
order, and update HID's last-report cache only after notification acceptance.
`0x4EC4(id,type)` selects the current protocol mapping; `0x72AA(conn,cccdTable)`
checks that report's subscription. Global readiness alone is insufficient.

Control's logical ABI is `(parameter,length,value)`. Parameter zero is supported;
other parameters return 2. Proven callers pass either `(0,0,NULL)` or
`(0,1,&one)`. The latter pointer belongs to the caller's stack. Native cleanup
terminates via `0x39E6`, resets legacy queue indexes, then invokes
`0x34B8(0x10,0x1151D,0x409,length,value)` with **five arguments**. The setter's
`0x11602` branch distinguishes normal from forced bond erasure. Caller `0x25BC`
requests forced erasure immediately before a reset flag; it cannot safely wait
for asynchronous completion. Neither active path should call the old direct-HID
neutral branch at `0x4910..0x4950`.

## RAM, identity and measurement limits

APP, HID, UART and the 36-byte legacy queue are at `0x20000928`, `0x20000AD8`,
`0x20000DD0`, `0x200027C8`. The queue becomes an exclusive magic/pointer header
only after successful initialization and empty-mailbox checks. Inactive hooks
must leave its contents and original producer/drain behavior intact.

Heap initialization uses literals `0x3598 = 0x2000306B` and
`0x3594 = 0x200041FF`; `0x2BD6` aligns its start to `0x20003068`.
`0x20004200..0x20004400` is a stack region, not spare storage. Allocation/free
are `0x2C3E`/`0x2CD0`; statistics are `0x2D54`. Its largest-block query coalesces
free blocks, so call it outside the adapter's critical gate. Reuse native gate
`0x2BAA`/`0x2BC0(token)` only for bounded state operations, never BLE/NVRAM calls.

Task constructors are more restrictive than the reset stack: `0x13AE` supplies
APP priority 1, stack `0x200022F8..0x200025E6`, **750 bytes**, then function
`0x1735`; `0x4670` supplies HID priority 2, stack
`0x20002638..0x200027C8`, **400 bytes**, then function `0x46A5`. Their parameter
stores are at `0x13C6..0x13D0` and `0x4688..0x4692`, through Task constructor
thunk `0x1340`. The native APP/HID loops retain 24/32-byte frames respectively.

Instruction-level stack observations include real decoding, C and native report
serialization. The inline HID test includes its native 32-byte frame and the
bridge's 32-byte save: its observed prefix uses 240 bytes with external API
fixtures. The refactored worker performs no bond-count/NV-record query. At its
notification API boundary, 168 bytes are already used. Visible nested frames
`0x34B8` (56), `0x3322` (48), `0x31B0` (24), `0x2DAE` (16), `0x2BAA` (8)
bring that path to **320 bytes before unknown ROM/context-save usage**. The
rear shift sequence reaches 272 bytes in the fixture, plus APP's retained 24.
These are partial software measurements, not a proven native worst-case bound;
ROM calls, preemption and exception handling still need stack-canary evidence.

Bond count `0x40E` plus saved slot-zero address `0x419` does not identify the
current link. Compare all six saved bytes with `0x3874(0x315,out)`, which copies
the current peer address from native GAP state+`0x114`. Unknown, multiple or
unresolved private addresses fail closed. Hash tags do not replace that full
comparison. Actual identity and memory headroom still require hardware checks.

Heap minimum means **minimum sampled value**, not a continuous low-water mark.
UART timing uses logical flag 6, which differs from open-driver flag 5; neither
measures electrical consumption. Tick-delta accounting handles one 32-bit wrap,
but cannot reconstruct multiple unobserved wraps during long idle. Compilation
and emulation cannot establish radio reliability, overnight wake, battery life,
worst-case stack use or OTA recovery.
