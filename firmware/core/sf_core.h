#ifndef SF_CORE_H
#define SF_CORE_H
#include <stdint.h>
#include <stddef.h>

#define SF_FIFO_CAPACITY 16u
#define SF_RUNTIME_MAX 640u
#define SF_PRESS_TTL_MS 2000u
#define SF_REPORT_KEYBOARD 1u
#define SF_REPORT_CONSUMER 2u
#define SF_CCCD_KEYBOARD 1u
#define SF_CCCD_CONSUMER 2u

enum SfSourceKind { SF_SOURCE_FRONT=1, SF_SOURCE_KEYBOARD=2,
                    SF_SOURCE_UART=3, SF_SOURCE_ORIENTATION=4 };
enum SfSubmit { SF_ADMITTED=0, SF_DUPLICATE=1, SF_FULL=2,
                SF_INVALID=3, SF_QUARANTINED=4, SF_NO_PEER=5 };
enum SfSendResult { SF_SEND_ACCEPTED=0, SF_SEND_RETRYABLE=1,
                    SF_SEND_UNAVAILABLE=2 };

typedef struct { uint8_t kind, count, payload[5], reserved; } SfSourceEvent;
typedef struct { uint32_t tick; uint16_t epoch; uint8_t id,len,data[8]; } SfTx;
typedef struct { SfTx frame; uint32_t token; } SfTxView;

/* Adapter must serialize EVERY call using the native critical-section gate.
 * Copy a peek result, leave the gate, call BLE, then reenter for complete.
 * No adapter, allocator, radio or RTOS calls occur inside this core. */
typedef struct SfCore {
    SfSourceEvent source[SF_FIFO_CAPACITY];
    SfTx tx[SF_FIFO_CAPACITY];
    uint32_t peer, token, retry_started, retry_due;
    uint32_t dropped_source, dropped_tx, expired, invalid, retries;
    uint16_t epoch;
    uint8_t source_head,source_count,tx_head,tx_count;
    uint8_t connected,cccd,protocol,repair_mask,quarantine_mask,release_mask;
    uint8_t admitted_mask,admitted[2][8],accepted[2][8];
    uint8_t flight_id,flight_repair,flight_len,flight_pos,flight_data[8];
    uint8_t retry_step,retry_active,wait_event;
    uint8_t parser[6],parser_count,source_barrier;
} SfCore;

_Static_assert(sizeof(SfSourceEvent)==8, "source ABI");
_Static_assert(sizeof(SfTx)==16, "TX ABI");
_Static_assert(sizeof(SfCore)<=SF_RUNTIME_MAX, "runtime allocation ceiling");

void sf_core_init(SfCore *c, uint32_t now);
uint32_t sf_core_size(SfCore *c);
int sf_source_push(SfCore *c, const SfSourceEvent *event);
int sf_source_pop(SfCore *c, SfSourceEvent *event);
uint32_t sf_uart_feed(SfCore *c, const uint8_t *data, uint32_t len);
int sf_front_index_valid(SfCore *c, uint8_t index);
/* A nonzero peer tag denotes the adapter's verified bonded identity, not its
 * connection handle. Set it even while disconnected before admitting inputs. */
void sf_link(SfCore *c, uint8_t connected, uint32_t peer, uint32_t now);
void sf_cccd(SfCore *c, uint8_t mask, uint32_t now);
void sf_protocol(SfCore *c, uint8_t mode, uint32_t now);
enum SfSubmit sf_submit(SfCore *c, uint8_t id, uint8_t len,
                        const uint8_t *data, uint32_t now);
uint32_t sf_tx_peek(SfCore *c, uint32_t now, SfTxView *out);
int sf_tx_complete(SfCore *c, uint32_t token, enum SfSendResult result,
                   uint32_t now);
/* Call only for a useful resource/readiness/new-input event, not every timer. */
void sf_wake(SfCore *c, uint32_t now);
void sf_repair(SfCore *c, uint8_t mask, uint32_t now);

#endif
