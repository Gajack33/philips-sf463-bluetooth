# Freestanding HID reliability core

`sf_core.c` is compiled C shared by host tests and the Thumb image. It has no
mutable globals, allocator, libc, radio calls or RTOS calls. `sizeof(SfCore)` is
488 bytes on the tested host and ARM ABI; the header rejects layouts above 640.
The native adapter owns allocation, verified peer identity, synchronization,
timers, notification-status translation and the actual BLE calls.

## Adapter contract

- Serialize every API entry with the firmware's native critical-section gate.
  `sf_tx_peek` copies a frame and token. Release the gate before BLE, then enter
  it again for `sf_tx_complete`. A stale completion token is ignored.
- Call `sf_link` with the actual bonded identity tag, including while offline.
  Zero identity admits no reports. A connection handle is not an identity tag.
- Update `sf_cccd` with mask 1 for keyboard and 2 for consumer notifications.
  Update `sf_protocol` with HID protocol mode 0 or 1. Mode 0 blocks consumer data.
- Submit keyboard report ID 1 with exactly 8 bytes, consumer ID 2 with exactly
  3. `SF_ADMITTED` includes reserved neutral repairs. `SF_DUPLICATE` is already
  admitted. Every other submit result must leave the caller's cache unchanged.
- Only the worker calls peek/complete. `SF_SEND_ACCEPTED` means the native stack
  accepted the notification; it is not an application-level delivery ACK.
  Accepted reports are never retried. `SF_SEND_RETRYABLE` uses 20/50/100/200 ms
  backoff. `SF_SEND_UNAVAILABLE` waits for a useful event via `sf_wake`.
- Arm a timer from `retry_due` only while `retry_active` is set. After two seconds
  of active failure, repair obligations remain latched without periodic polling.
  `wait_event` is a report-ID bitmask, not a global Boolean.
- Call `sf_repair(mask,now)` for native input loss. A source FIFO overflow does
  this automatically for both report IDs, fences the ambiguous backlog and drops
  it at the next pop. New reports stay quarantined until their zero is accepted.

The source and TX capacities are both 16. Full queues never overwrite old slots.
TX overflow rejects new presses; an unqueueable release uses its reserved neutral
repair instead. Report order is preserved within each report ID; an unavailable
consumer report does not stop keyboard traffic. Two-second expiry applies only to
unsent presses. Accepted nonzero state creates a release obligation until a zero
is accepted or that connection ends. CCCD/protocol transitions require a neutral
frame before fresh input and do not replay old commands across connection epochs
or bonded peers.

The parser accepts six-byte `FE flags kind payload[3]` frames, keeps partial reads
and resynchronizes malformed frames to a following FE. Valid payload FE bytes are
preserved. It emits `SF_SOURCE_UART`, count 5, payload
`[flags,kind,payload0,payload1,payload2]`. Native event kinds 0/1/2 and FA/FB/FF are
retained. Front indexes 45 through 254 are rejected; 0..44 and FF are valid.
The adapter must clear the parser on a verified UART reset; partial-frame timeouts
are outside this timestamp-free parser API.

## Verification

Compile the host suite with an existing GCC:

```sh
gcc -std=c11 -Wall -Wextra -Werror -O2 -fsanitize=address,undefined \
    sf_core.c test_sf_core.c -o /tmp/test_sf_core
/tmp/test_sf_core
```

The 16 named tests cover tagged source order and overflow fencing, fragmented
UART recovery, all front index boundaries, worker/token ownership, no accepted
Power replay, admission-cache correctness, mixed keyboard/consumer saturation,
release persistence beyond press expiry, retry timing and event recovery,
per-report unavailability, connection/peer/CCCD/protocol transitions, all eight
keyboard bytes, overflow during an in-flight press, and preserving the newest valid pending report after initial neutralization or older-press expiry.

Thumb compile flags include `-target arm-freestanding-eabi -mcpu=cortex_m3 -mthumb
-ffreestanding -fno-builtin -fno-stack-protector -fno-unwind-tables
-fno-asynchronous-unwind-tables -Oz`. The resulting object has no undefined
symbols. Host tests and compilation do not validate native interrupt scheduling,
heap headroom, BLE API contracts, radio delivery, battery life or wake from sleep.
