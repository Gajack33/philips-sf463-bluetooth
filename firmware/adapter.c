/* Native SF463 adapter. Every fixed address is an audited 06.05/06.07 ABI.
 * No writable global, new IRQ, permanent task or per-key allocation is used.
 * Audio, OTA, RF configuration and the bootloader are not patched here.
 */
#include "core/sf_core.h"
#include <stdint.h>

#define APP ((volatile uint8_t *)0x20000928u)
#define HID ((volatile uint8_t *)0x20000ad8u)
#define UART ((volatile uint8_t *)0x20000dd0u)
#define LEGACY_QUEUE ((volatile uint32_t *)0x200027c8u)
#define CORE_MAGIC 0x53465243u
#define NATIVE_FN(address,type) ((type)(uintptr_t)((address)|1u))
#define FN0(a) NATIVE_FN(a,uint32_t(*)(void))
#define FN1(a) NATIVE_FN(a,uint32_t(*)(uint32_t))
#define FN2(a) NATIVE_FN(a,uint32_t(*)(uint32_t,uint32_t))
#define FN3(a) NATIVE_FN(a,uint32_t(*)(uint32_t,uint32_t,uint32_t))
#define FN4(a) NATIVE_FN(a,uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))
#define FN5(a) NATIVE_FN(a,uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))

enum RcInitReason {
    RC_INIT_UNKNOWN=0, RC_INIT_NO_HID_SEMAPHORE=1, RC_INIT_BOND_COUNT=2,
    RC_INIT_BOND_RPC=3, RC_INIT_ZERO_IDENTITY=4, RC_INIT_TOTAL_FREE=5,
    RC_INIT_LARGEST_BLOCK=6, RC_INIT_ALLOC_NULL=7, RC_INIT_POST_FREE=8,
    RC_INIT_HID_QUEUE=9, RC_INIT_APP_MAILBOX=10,
    RC_INIT_NATIVE_TX_ACTIVE=11, RC_INIT_REAR_SOURCE_UNRESOLVED=12
};
#if RC_DIAGNOSTIC
static void init_snapshot(uint8_t reason,uint8_t bonds,uint32_t free_bytes,uint32_t largest,uint8_t deferred);
static void init_snapshot_locked(uint8_t reason,uint8_t bonds,uint32_t free_bytes,uint32_t largest,uint8_t deferred);
#define INIT_SNAPSHOT(reason,bonds,free_bytes,largest) init_snapshot(reason,bonds,free_bytes,largest,(uint8_t)!boot)
#define INIT_SNAPSHOT_LOCKED(reason,bonds,free_bytes,largest) init_snapshot_locked(reason,bonds,free_bytes,largest,(uint8_t)!boot)
#else
#define INIT_SNAPSHOT(reason,bonds,free_bytes,largest) ((void)0)
#define INIT_SNAPSHOT_LOCKED(reason,bonds,free_bytes,largest) ((void)0)
#endif

typedef struct {
    SfCore core;
    uint32_t tick_last, milliseconds, tick_remainder;
    uint32_t accounted_at, connected_ms, uart_ms, idle_ms;
    uint32_t connection_changes, last_front_index, partial_reads;
    uint16_t minimum_free, last_handle;
    uint8_t last_role, last_uart, identity_verified, diag_page;
    uint8_t bond_address[6], last_connected_address[6];
    uint32_t control_started;
    uint8_t control_pending, control_fenced, control_length, control_value, clock_initialized;
    uint16_t dispatch_epoch;
    uint8_t dispatch_active, bond_valid;
    uint32_t source_ticks[16];
    uint8_t dispatch_expired;
    uint32_t pending_rear_tick;
    uint16_t pending_rear_epoch;
    uint8_t pending_rear_index, handoff_mask;
} RcState;
_Static_assert(sizeof(RcState)<=640,"one allocation including all adapter state");
_Static_assert(offsetof(RcState,handoff_mask)==639,"handoff uses existing tail padding");

extern uint64_t rc_original_rear(uint32_t,const uint8_t *);
extern uint64_t rc_original_front(uint32_t,const uint8_t *,uint32_t);
extern void rc_original_event_drain(void);
extern void rc_original_consumer(uint32_t);
extern void rc_original_keyboard(uint32_t,const uint8_t *);
extern uint32_t rc_original_hid_submit(uint32_t,uint32_t,uint32_t,const uint8_t *);
extern uint64_t rc_original_link_event(uint32_t,uint32_t,uint32_t,uint32_t);
extern uint64_t rc_original_hid_message(const uint8_t *,uint32_t,uint32_t,uint32_t);
extern uint64_t rc_original_attr_write(uint32_t,uintptr_t,const uint8_t *,uint32_t,uint32_t);
extern uint64_t rc_original_uart_receive(void);
extern void rc_original_timer(void);
extern uint32_t rc_original_control(uint32_t,uint32_t,const uint8_t *);
extern void rc_original_uart_close(void);
extern void rc_original_uart_worker(void);
extern uint32_t rc_original_device_info(uint32_t,uintptr_t,uint8_t *,uint16_t *,uint16_t,uint8_t);
extern void rc_native_event_rest(uint32_t mask);
extern void rc_native_uart_frame(const uint8_t *frame);

static void copy(uint8_t *to,const uint8_t *from,uint32_t n) { while(n--) *to++=*from++; }
static void clear(uint8_t *to,uint32_t n) { while(n--) *to++=0; }
static int equal(const uint8_t *a,const uint8_t *b,uint32_t n) {
    while(n--) if(*a++!=*b++) return 0;
    return 1;
}
static int nonzero(const uint8_t *p,uint32_t n) { while(n--) if(*p++) return 1; return 0; }
static uint32_t get32(volatile const uint8_t *base,uint32_t at) {
    return *(volatile const uint32_t *)(base+at);
}
static uint16_t get16(volatile const uint8_t *base,uint32_t at) {
    return *(volatile const uint16_t *)(base+at);
}
static int ram_word(uint32_t p) { return !(p&3u) && p>=0x20000000u && p<=0x20004ffcu; }
#if RC_DIAGNOSTIC
static int uuid_halfword(uint32_t p) {
    return !(p&1u) && ((p>=0x60u && p<=0x1cffeu) || (p>=0x20000000u && p<=0x20004ffeu));
}
#endif
static uint32_t lock(void) { return FN0(0x2baa)(); }
static void unlock(uint32_t token) { FN1(0x2bc0)(token); }
static RcState *state(void) {
    uint32_t p;
    if(LEGACY_QUEUE[0]!=CORE_MAGIC) return (RcState *)0;
    p=LEGACY_QUEUE[1];
    if((p&3u) || p<0x2000306cu || p>0x20004200u-sizeof(RcState)) return (RcState *)0;
    return (RcState *)(uintptr_t)p;
}
uint32_t rc_enabled(void) { return state()!=0; }
uint32_t rc_runtime_size(void) { return sizeof(RcState); }
static uint32_t ticks(void) { return FN0(0x2b8c)(); }
/* Native Clock_getTicks is 32 bits at 10us. Accumulate deltas instead of
 * dividing its absolute value, including a wrap and sub-ms remainder. */
static uint32_t now_locked(RcState *s) {
    uint32_t current=ticks(),delta=current-s->tick_last;
    uint32_t whole=delta/100u,part=delta%100u+s->tick_remainder;
    s->tick_last=current;
    s->milliseconds+=whole+part/100u;
    s->tick_remainder=part%100u;
    return s->milliseconds;
}
static uint8_t source_release_mask(const SfSourceEvent *event) {
    uint8_t kind=event->kind,count=event->count;
    const uint8_t *p=event->payload;
    if(kind==SF_SOURCE_UART && count==5u) { kind=SF_SOURCE_FRONT; count=p[1]; p+=2; }
    if(kind!=SF_SOURCE_FRONT && kind!=SF_SOURCE_KEYBOARD) return 0;
    if(count && (count!=1u || p[0]!=255u)) return 0;
    return kind==SF_SOURCE_FRONT?2u:1u;
}
static void source_release_after_purge_locked(RcState *s) {
    if(!s->core.source_barrier) {
        s->handoff_mask&=(uint8_t)~((s->handoff_mask>>4)&3u);
        s->handoff_mask&=3u;
    }
}
static void source_push_locked(RcState *s,const SfSourceEvent *event) {
    uint32_t pos=(s->core.source_head+s->core.source_count)&15u;
    if(sf_source_push(&s->core,event)) s->source_ticks[pos]=now_locked(s);
    else if(s->core.source_barrier)
        s->handoff_mask|=(uint8_t)(source_release_mask(event)<<4);
}
static void account_locked(RcState *s,uint32_t now) {
#if RC_DIAGNOSTIC
    uint32_t elapsed=now-s->accounted_at;
    if(s->last_role==6u) s->connected_ms+=elapsed;
    if(s->last_uart) s->uart_ms+=elapsed;
    else s->idle_ms+=elapsed;
    s->accounted_at=now;
    s->last_uart=(UART[6]!=0);
#else
    (void)s; (void)now;
#endif
}
static void post_app(void) { uint32_t sem=get32(APP,0x2c); if(sem) FN2(0x60)(sem,0x100); }
static void post_hid(void) { uint32_t sem=get32(HID,0x1c); if(sem) FN2(0x60)(sem,4); }
static void sample_heap(RcState *s) {
#if RC_DIAGNOSTIC
    uint32_t stats[3],token;
    /* The allocator may lock internally: never sample it inside our gate. */
    NATIVE_FN(0x2d54,void(*)(uint32_t *))(stats);
    token=lock();
    if(stats[1]<s->minimum_free) s->minimum_free=(uint16_t)stats[1];
    unlock(token);
#else
    (void)s;
#endif
}
static uint8_t bonded_count(void) { return (uint8_t)FN0(0x26ee)(); }
static int stored_peer(uint8_t out[6]) {
    uint32_t route=*(const uint32_t *)(uintptr_t)0x2b14u;
    uint8_t nonzero=0,i;
    clear(out,6);
    /* 0x419 resolves NV bond slot zero, NOT a connection handle/target. */
    if(bonded_count()!=1u || FN4(0x34b8)(0x10,route,0x419,(uint32_t)(uintptr_t)out)) return 0;
    for(i=0;i<6;++i) nonzero|=out[i];
    return nonzero!=0;
}
static int current_peer(uint8_t out[6]) {
    clear(out,6);
    return FN2(0x3874)(0x315,(uint32_t)(uintptr_t)out)==0;
}
static uint32_t peer_tag(const uint8_t address[6]) {
    uint32_t hash=2166136261u,i;
    for(i=0;i<6;++i) hash=(hash^address[i])*16777619u;
    return hash?hash:1u;
}
static uint8_t cccd_mask(void) {
    uint8_t mask=0,id;
    for(id=1;id<=2;++id) {
        uint32_t entry=FN2(0x4ec4)(id,1),attr,pointer,table;
        if(!ram_word(entry) || entry>0x20004ff0u) continue;
        attr=*(const uint32_t *)(uintptr_t)(entry+4);
        if(!ram_word(attr) || attr>0x20004ff0u) continue;
        pointer=*(const uint32_t *)(uintptr_t)(attr+12);
        if(!ram_word(pointer)) continue;
        table=*(const uint32_t *)(uintptr_t)pointer;
        if(!ram_word(table)) continue;
        if(FN2(0x72aa)(get16(HID,0x18),table)&1u) mask|=(uint8_t)(1u<<(id-1));
    }
    return mask;
}
/* Native calls and NVRAM queries are deliberately outside the critical gate.
 * A current address must match the sole saved identity before queued data is
 * sent. Unknown/multiple/RPA identities are not treated as a verified peer. */
static void refresh(RcState *s,int useful,int query_bond) {
    uint8_t saved[6],connected[6],valid;
    uint32_t token;
    /* The HID task has only 400 bytes of stack. NV/ICall bond queries run in
     * APP (750 bytes); HID lifecycle callbacks use the cached full identity.
     * Current address, role/handle, protocol and CCCD are still checked before
     * every worker pass. No connection handle is used as an identity. */
    if(query_bond) valid=(uint8_t)stored_peer(saved);
    else {
        token=lock(); copy(saved,s->bond_address,6); valid=s->bond_valid; unlock(token);
    }
    uint8_t role=HID[0xd],verified=(valid && role==6u && current_peer(connected) && equal(saved,connected,6));
    uint8_t mask=verified?cccd_mask():0;
    uint8_t mode=*(volatile const uint8_t *)0x20001790u;
    uint32_t now;
    token=lock(); now=now_locked(s);
    account_locked(s,now);
    if(!query_bond && (valid!=s->bond_valid || !equal(saved,s->bond_address,6))) {
        valid=0; verified=0; mask=0; /* Cached snapshot changed while outside. */
    }
    if(query_bond && valid && !equal(saved,s->bond_address,6)) {
        sf_link(&s->core,0,0,now); /* Full compare avoids hash collision reuse. */
        copy(s->bond_address,saved,6);
    }
    if(query_bond) s->bond_valid=valid;
    if(s->control_fenced && !s->control_pending) { verified=0; mask=0; }
    if(s->core.connected && get16(HID,0x18)!=s->last_handle)
        sf_link(&s->core,0,s->core.peer,now);
#if RC_DIAGNOSTIC
    if(role!=s->last_role || get16(HID,0x18)!=s->last_handle) ++s->connection_changes;
#endif
    s->last_role=role;
    s->last_handle=get16(HID,0x18);
    if(HID[0x16]) s->clock_initialized=1;
    s->identity_verified=verified;
    if(!s->control_pending && role!=6u) s->control_fenced=0;
    if(verified) copy(s->last_connected_address,connected,6);
    if(s->core.connected!=verified || s->core.peer!=(valid?peer_tag(saved):0))
        sf_link(&s->core,verified,valid?peer_tag(saved):0,now);
    if(s->core.protocol!=mode) sf_protocol(&s->core,mode,now);
    if(s->core.cccd!=mask) sf_cccd(&s->core,mask,now);
    if(useful) {
        sf_wake(&s->core,now);
    }
    unlock(token);
}
/* APP is the sole admission owner. A useful lifecycle event or a proven
 * physical rear release may retry refusal, never a press, timer or HID callback.
 * Diagnostic telemetry records the latest refusal and its boot/deferred scope. */
static void try_admit(uint32_t boot,uint32_t released_rear) {
    uint32_t stats[3],i,token;
    uint8_t address[6],bonds;
    RcState *s;
    /* No native queue byte is changed before allocation and identity checks. */
    if(LEGACY_QUEUE[0]==CORE_MAGIC) return;
    if(!get32(HID,0x1c)) {
        INIT_SNAPSHOT(RC_INIT_NO_HID_SEMAPHORE,255,65535,65535); return;
    }
    /* HID's patched4784 copies the whole next legacy slot to its own stack
     * before publishing a consumed index. A suspended native send therefore
     * holds no pointer into the36-byte queue. Persistent readiness0E is not
     * a busy flag and retains its native meaning. APP alone owns admission
     * and native producers, so it cannot claim during its own4FAA enqueue. */
    /* Native1FDA can retain APP1B when UART is unready even on a release.
     * Do not infer physical release from that stale logical/cache state.
     * Only the real rear source call188C may supply local release proof. */
    if(APP[0x1b]!=255u && !released_rear) {
        INIT_SNAPSHOT(RC_INIT_REAR_SOURCE_UNRESOLVED,255,65535,65535); return;
    }
    bonds=bonded_count();
    if(bonds!=1u) { INIT_SNAPSHOT(RC_INIT_BOND_COUNT,bonds,65535,65535); return; }
    clear(address,6);
    if(FN4(0x34b8)(0x10,*(const uint32_t *)(uintptr_t)0x2b14u,0x419,(uint32_t)(uintptr_t)address)) {
        INIT_SNAPSHOT(RC_INIT_BOND_RPC,bonds,65535,65535); return;
    }
    if(!nonzero(address,6)) { INIT_SNAPSHOT(RC_INIT_ZERO_IDENTITY,bonds,65535,65535); return; }
    NATIVE_FN(0x2d54,void(*)(uint32_t *))(stats);
    if(stats[1]<sizeof(RcState)+8u+768u) {
        INIT_SNAPSHOT(RC_INIT_TOTAL_FREE,bonds,stats[1],stats[2]); return;
    }
    if(stats[2]<sizeof(RcState)) {
        INIT_SNAPSHOT(RC_INIT_LARGEST_BLOCK,bonds,stats[1],stats[2]); return;
    }
    s=(RcState *)(uintptr_t)FN1(0x2c3e)(sizeof(RcState));
    if(!s) { INIT_SNAPSHOT(RC_INIT_ALLOC_NULL,bonds,stats[1],stats[2]); return; }
    NATIVE_FN(0x2d54,void(*)(uint32_t *))(stats);
    if(stats[1]<768u) {
        INIT_SNAPSHOT(RC_INIT_POST_FREE,bonds,stats[1],stats[2]);
        FN1(0x2cd0)((uint32_t)(uintptr_t)s); return;
    }
    clear((uint8_t *)s,sizeof(*s));
    s->pending_rear_index=255;
    sf_core_init(&s->core,0);
    s->tick_last=ticks();
    s->minimum_free=(uint16_t)stats[1];
    s->last_handle=get16(HID,0x18);
    copy(s->bond_address,address,6);
    s->bond_valid=1;
    sf_link(&s->core,0,peer_tag(address),0);
    token=lock();
    /* Recheck after EVERY RPC/heap call. The native reader snapshots under
     * this same gate before it can make a queue look empty. If a claim
     * occurs while it waits in RPC, its return bypasses all legacy postlude. */
    if(LEGACY_QUEUE[0]==CORE_MAGIC) {
        unlock(token); FN1(0x2cd0)((uint32_t)(uintptr_t)s); return;
    }
    if(HID[0x14]!=HID[0x15] || (get16(APP,0x20)&0x11u)) {
        INIT_SNAPSHOT_LOCKED(HID[0x14]!=HID[0x15]?RC_INIT_HID_QUEUE:RC_INIT_APP_MAILBOX,
                             bonds,stats[1],stats[2]);
        unlock(token); FN1(0x2cd0)((uint32_t)(uintptr_t)s); return;
    }
    if(APP[0x1b]!=255u && !released_rear) {
        INIT_SNAPSHOT_LOCKED(RC_INIT_REAR_SOURCE_UNRESOLVED,bonds,stats[1],stats[2]);
        unlock(token); FN1(0x2cd0)((uint32_t)(uintptr_t)s); return;
    }
    /* A source still held with a matching native attempt/dedupe cache must
     * not become a fresh action after the native in-flight report returns.
     * These sentinels and attempted caches are never accepted-report evidence.
     * F1/index44 is hold-only pairing, not an ordinary Consumer press. */
    if(APP[0x18]<44u && get16(APP,0x28) &&
       get16(APP,0x28)==*(volatile const uint16_t *)0x20003044u) s->handoff_mask|=2u;
    if(released_rear) { APP[0x1b]=255u; APP[0x17]=255u; }
    /* Exclusive claim: all native queue producer/drain accessors are hooked.
     * Low byte of the marker is not a valid native report ID, preventing an
     * accidental match with ordinary legacy queue contents after fallback. */
    for(i=0;i<9;++i) LEGACY_QUEUE[i]=0;
    HID[0x14]=HID[0x15]=0;
    LEGACY_QUEUE[1]=(uint32_t)(uintptr_t)s;
    LEGACY_QUEUE[0]=CORE_MAGIC;
#if RC_DIAGNOSTIC
    /* A later loss of the claim must not expose an older admission refusal as if
     * it were the cause. Active reads render their normal pages on demand. */
    ((volatile uint8_t *)0x20000664u)[0]=0;
#endif
    unlock(token);
    refresh(s,1,0);
    if(!boot) { post_app(); post_hid(); }
}
void rc_app_init(void) {
    NATIVE_FN(0x13e4,void(*)(void))();
    try_admit(1,0);
}
/* Called only at nativeAPP1796, with that turn's consumed Event mask (R5).
 * The existing native tail still runs once, including on ordinary wakes. */
void rc_app_turn(uint32_t events) {
    FN0(0x2ae6)();
    if(events&0x400u) try_admit(0,0);
}
/* Called only instead of BL1FDA at188C: R5 identifies the consumed source.
 * The replay/tap calls198E/199C are deliberately not wrapped. The shared
 * mailbox cannot identify either face when both source bits were pending. */
void rc_rear_source_decode(uint32_t count,const uint8_t *payload,uint32_t mask) {
    uint32_t released=((mask&0x91u)==0x10u &&
        (!count || (count==1u && payload && payload[0]==255u)));
    uint32_t useful=(APP[0x1b]!=255u || APP[0x17]!=255u);
    NATIVE_FN(0x1fda,void(*)(uint32_t,const uint8_t *))(count,payload);
    if(released && useful && !state()) try_admit(0,1);
}
uint64_t rc_hid_message(const uint8_t *message,uint32_t b,uint32_t c,uint32_t d) {
    uint32_t useful=0;
    uint16_t type=get16(message,0);
    uint8_t phase=message[2];
    if(type==1u) useful=(phase==6u && HID[0x0d]!=6u);
    else if(type==8u && (phase==1u || phase==2u) && HID[0x11]!=phase) {
        /* The native dispatcher frees this status byte before returning. */
        useful=(*(const uint8_t *)(uintptr_t)get32(message,4)==0u);
    }
    if(!useful) return rc_original_hid_message(message,b,c,d);
    uint64_t result=rc_original_hid_message(message,b,c,d);
    if(LEGACY_QUEUE[0]!=CORE_MAGIC) {
        uint32_t sem=get32(APP,0x2c);
        if(sem) FN2(0x60)(sem,0x400);
    }
    return result;
}
uint64_t rc_rear_callback(uint32_t count,const uint8_t *payload) {
    RcState *s=state();
    SfSourceEvent event;
    uint32_t token;
    if(!s) return rc_original_rear(count,payload);
    if(count==255u) return 0;
    if(s->control_fenced) return 0;
    clear((uint8_t *)&event,sizeof(event));
    event.kind=SF_SOURCE_KEYBOARD;
    if(count>5u || (count && !payload)) return 0;
    event.count=(uint8_t)count;
    copy(event.payload,payload,count);
    token=lock(); source_push_locked(s,&event); unlock(token);
    post_app();
    return 0;
}
uint64_t rc_front_callback(uint32_t count,const uint8_t *payload,uint32_t special) {
    RcState *s=state();
    SfSourceEvent event;
    uint32_t token;
    if(!s) return rc_original_front(count,payload,special);
    if(special==1u) { uint32_t sem=get32(APP,0x2c); if(sem) FN2(0x60)(sem,0x200); return 0; }
    if(s->control_fenced) return 0;
#if RC_DIAGNOSTIC
    if(!special && count==1u && payload && payload[0]<45u) {
        token=lock(); s->last_front_index=0x100u|payload[0]; unlock(token);
    }
#endif
    /* Only the native parser running synchronously in the APP worker has
     * these return sites. Decode its derived orientation/key immediately:
     * appending them behind a later rear event would reorder the source FIFO.
     * The IRQ's special-1 callback returns to 0x5702, so still just posts work.
     */
    token=(uint32_t)(uintptr_t)__builtin_return_address(0)&~1u;
    if(token==0x555au || token==0x5568u || token==0x5608u) {
        if(s->dispatch_expired && !special && count && payload && payload[0]!=255u) return 0;
        NATIVE_FN(0x1dac,void(*)(uint32_t,const uint8_t *,uint32_t))(count,payload,special);
        if(!special && (!count || (count==1u && payload && payload[0]==255u))) {
            token=lock(); s->handoff_mask&=(uint8_t)~2u; unlock(token);
        }
        return 0;
    }
    if(special && special!=0xf1u) return 0;
    if(count>2u || (!payload && (count || special))) return 0;
    clear((uint8_t *)&event,sizeof(event));
    event.kind=special?SF_SOURCE_ORIENTATION:SF_SOURCE_FRONT;
    event.count=(uint8_t)count;
    copy(event.payload,payload,special?1u:count);
    token=lock(); source_push_locked(s,&event); unlock(token);
    post_app();
    return 0;
}
/* Native APP+17 is a second, one-key queue outside SfCore. Its retained scan
 * code inherits the original source timestamp and session, never a fresh TTL.
 * Only APP accesses this byte; the epoch can change from a HID callback. */
static void pending_rear_check_locked(RcState *s,uint32_t now) {
    if(APP[0x17]==255u) { s->pending_rear_index=255; return; }
    if(s->pending_rear_index==255u || s->pending_rear_index!=APP[0x17] ||
       s->pending_rear_epoch!=s->core.epoch || now-s->pending_rear_tick>=SF_PRESS_TTL_MS) {
        if(s->pending_rear_index==APP[0x17] && s->pending_rear_epoch==s->core.epoch &&
           now-s->pending_rear_tick>=SF_PRESS_TTL_MS) ++s->core.expired;
        APP[0x17]=255; s->pending_rear_index=255;
        sf_repair(&s->core,1,now);
    }
}
void rc_event_drain(void) {
    RcState *s=state();
    SfSourceEvent event;
    uint32_t token,mask,processed=0,available,source_tick;
    if(!s) { rc_original_event_drain(); return; }
    do {
        token=lock();
        {
            uint32_t now=now_locked(s);
            pending_rear_check_locked(s,now);
            source_tick=s->source_ticks[s->core.source_head];
            uint32_t age=now-source_tick;
            source_release_after_purge_locked(s);
            available=(uint32_t)sf_source_pop(&s->core,&event);
            /* A real release refused by a source-overflow barrier is still
             * evidence of physical release, but only after the old FIFO has
             * been purged. A suspended old dispatch is fenced below. */
            source_release_after_purge_locked(s);
            s->dispatch_epoch=s->core.epoch; s->dispatch_active=(uint8_t)available;
            s->dispatch_expired=(uint8_t)(available && age>=SF_PRESS_TTL_MS);
            if(s->dispatch_expired) {
                ++s->core.expired;
                sf_repair(&s->core,event.kind==SF_SOURCE_KEYBOARD?1u:2u,s->milliseconds);
            }
        }
        unlock(token);
        if(!available) break;
        if(event.kind==SF_SOURCE_UART) {
            uint8_t frame[6]; frame[0]=0xfe; copy(frame+1,event.payload,5);
            token=lock(); account_locked(s,now_locked(s)); unlock(token);
            rc_native_uart_frame(frame); /* ACK/close/voice/face logic unchanged. */
            token=lock(); account_locked(s,now_locked(s)); unlock(token);
        } else if(event.kind==SF_SOURCE_KEYBOARD) {
            if(!s->dispatch_expired || !event.count)
                NATIVE_FN(0x1fda,void(*)(uint32_t,const uint8_t *))(event.count,event.payload);
            token=lock();
            if(APP[0x17]!=255u) {
                if(event.count==1u && !s->dispatch_expired && s->dispatch_epoch==s->core.epoch &&
                   APP[0x17]==event.payload[0]) {
                    s->pending_rear_tick=source_tick;
                    s->pending_rear_epoch=s->dispatch_epoch;
                    s->pending_rear_index=APP[0x17];
                } else {
                    /* A release must cancel a retained press even while UART
                     * readiness is false and native 1FDA cannot serialize it. */
                    APP[0x17]=255; s->pending_rear_index=255;
                    sf_repair(&s->core,1,now_locked(s));
                }
            } else s->pending_rear_index=255;
            unlock(token);
        } else if(event.kind==SF_SOURCE_ORIENTATION) {
            NATIVE_FN(0x1dac,void(*)(uint32_t,const uint8_t *,uint32_t))(event.count,event.payload,0xf1);
        } else {
            if((!s->dispatch_expired || !event.count || event.payload[0]==255u) &&
               (event.count!=1u || sf_front_index_valid(&s->core,event.payload[0])))
                NATIVE_FN(0x1dac,void(*)(uint32_t,const uint8_t *,uint32_t))(event.count,event.payload,0);
        }
        token=lock();
        if(s->dispatch_epoch==s->core.epoch)
            s->handoff_mask&=(uint8_t)~source_release_mask(&event);
        s->dispatch_active=0; s->dispatch_expired=0; unlock(token);
    } while(++processed<48u);
    token=lock(); pending_rear_check_locked(s,now_locked(s));
    mask=get16(APP,0x20); *(volatile uint16_t *)(APP+0x20)=0;
    /* Keep the generation guard active while native bit7 replays APP+17.
     * A link change discovered during its report submission cannot admit it. */
    s->dispatch_epoch=s->core.epoch;
    s->dispatch_active=(uint8_t)((mask&0x80u) && APP[0x17]!=255u);
    available=s->core.source_count; unlock(token);
    if(available) post_app();
    rc_native_event_rest(mask & ~0x11u);
    token=lock(); s->dispatch_active=0;
    if(APP[0x17]==255u) s->pending_rear_index=255;
    unlock(token);
    refresh(s,processed!=0,1);
    post_hid();
}
/* Serializer entrypoints never update a last-sent cache before admission. */
uint32_t rc_hid_submit(uint32_t id,uint32_t type,uint32_t length,const uint8_t *data) {
    RcState *s=state();
    enum SfSubmit result;
    uint32_t token,now;
    if(!s) return rc_original_hid_submit(id,type,length,data);
    if(s->control_fenced) return SF_QUARANTINED;
    if(type!=1u || id<1u || id>2u || length!=(id==1u?8u:3u) || !data) return SF_INVALID;
    refresh(s,1,1);
    token=lock(); now=now_locked(s);
    /* A HID-task connection callback can preempt APP after a source pop.
     * Its already-popped event must not be admitted into the new generation. */
    if(s->dispatch_active && (s->dispatch_epoch!=s->core.epoch ||
       ((s->dispatch_expired || s->core.source_barrier) && nonzero(data,length)))) result=SF_NO_PEER;
    else if((s->handoff_mask & (1u<<(id-1u))) && nonzero(data,length)) {
        ++s->core.dropped_tx; result=SF_QUARANTINED;
    }
    else result=sf_submit(&s->core,(uint8_t)id,(uint8_t)length,data,now);
    unlock(token);
    if(result==SF_ADMITTED || result==SF_DUPLICATE) {
        if(HID[0xd]!=6u && HID[0xd]!=2u) FN2(0x4bf8)(0,0);
        post_hid();
    }
    return result;
}
void rc_consumer(uint32_t usage) {
    uint8_t data[3];
    if(!state()) { rc_original_consumer(usage); return; }
    if(usage>0x7ffu) return;
    data[0]=(uint8_t)usage; data[1]=(uint8_t)(usage>>8); data[2]=0;
    (void)rc_hid_submit(2,1,3,data);
}
void rc_keyboard(uint32_t modifier,const uint8_t *keys) {
    uint8_t data[8];
    if(!state()) { rc_original_keyboard(modifier,keys); return; }
    if(!keys) return;
    data[0]=(uint8_t)modifier; data[1]=0; copy(data+2,keys,6);
    (void)rc_hid_submit(1,1,8,data);
}
static enum SfSendResult native_send(const SfTx *frame) {
    uint32_t entry,attr,pointer,table,status;
    if(HID[0xd]!=6u || !HID[0xe] || !HID[0x16]) return SF_SEND_UNAVAILABLE;
    entry=FN2(0x4ec4)(frame->id,1);
    if(!ram_word(entry) || entry>0x20004ff0u) return SF_SEND_UNAVAILABLE;
    attr=*(const uint32_t *)(uintptr_t)(entry+4);
    if(!ram_word(attr) || attr>0x20004ff0u) return SF_SEND_UNAVAILABLE;
    pointer=*(const uint32_t *)(uintptr_t)(attr+12);
    if(!ram_word(pointer)) return SF_SEND_UNAVAILABLE;
    table=*(const uint32_t *)(uintptr_t)pointer;
    if(!ram_word(table) || !(FN2(0x72aa)(get16(HID,0x18),table)&1u)) return SF_SEND_UNAVAILABLE;
    if(HID[0x13]) {
        /* Keep the native one-shot connection parameter request. */
        FN3(0x35d4)(0x319,1,(uint32_t)(uintptr_t)(HID+0x13));
        HID[0x13]=0;
    }
    /* Use real allocation+notification wrapper, not 0x4ef4's discarded status. */
    status=FN3(0x4f58)(*(const uint16_t *)(uintptr_t)entry,frame->len,(uint32_t)(uintptr_t)frame->data);
    if(status==0u) {
        HID[0]=frame->id; HID[1]=1; HID[2]=frame->len;
        copy((uint8_t *)(HID+3),frame->data,frame->len);
        if(frame->id==2u) *(volatile uint16_t *)0x20003044u=
            (uint16_t)(frame->data[0]|((uint16_t)frame->data[1]<<8));
        FN0(0x4bc8)(); return SF_SEND_ACCEPTED;
    }
    return status==0x13u?SF_SEND_RETRYABLE:SF_SEND_UNAVAILABLE;
}
static void native_control(uint32_t length,uint8_t value) {
    clear((uint8_t *)HID,12);
    if(HID[0xd]==6u) FN0(0x39e6)();
    HID[0x14]=HID[0x15]=0;
    FN5(0x34b8)(0x10,*(const uint32_t *)(uintptr_t)0x50d8u,0x409,length,
                length?(uint32_t)(uintptr_t)&value:0);
}
void rc_hid_worker(void) {
    RcState *s=state();
    uint32_t token,now,selected,iterations=0,arm=0,control=0,length=0,value=0;
    SfTxView view;
    enum SfSendResult result;
    if(!s) return; /* Assembly bridge retains native drain when inactive. */
    sample_heap(s);
    refresh(s,0,0);
    do {
        token=lock(); now=now_locked(s); selected=sf_tx_peek(&s->core,now,&view); unlock(token);
        if(!selected) break;
        result=native_send(&view.frame); /* Never execute stack calls in gate. */
        token=lock(); now=now_locked(s); sf_tx_complete(&s->core,view.token,result,now); unlock(token);
    } while(++iterations<16u);
    token=lock(); now=now_locked(s);
    if(HID[0x16]) s->clock_initialized=1;
    if(s->core.retry_active && !s->core.flight_id && (int32_t)(s->core.retry_due-now)>0)
        arm=s->core.retry_due-now;
    selected=(s->core.tx_count || s->core.repair_mask) && !s->core.retry_active && !s->core.wait_event;
    if(s->control_pending) {
        uint32_t elapsed=now-s->control_started;
        if((!s->core.release_mask && !s->core.flight_id) || elapsed>=2000u) {
            control=1; length=s->control_length; value=s->control_value;
            s->control_pending=0;
            s->bond_valid=0;
            /* A different generation cannot replay the cancelled commands. */
            sf_link(&s->core,0,0,now);
        } else if(!arm || arm>2000u-elapsed) arm=2000u-elapsed;
    }
    unlock(token);
    if(control) {
        /* Same native disconnect and erase-all-bonds call as 0x48f4, executed
         * only by this worker after neutral delivery or the bounded deadline.
         * The caller's stack byte was copied when the request was admitted. */
        native_control(length,(uint8_t)value);
        return;
    }
    /* Native readiness+16 can only be set after this Clock's callback ran.
     * Never arm an object merely because the APP task has initialized. */
    if(arm && s->clock_initialized && get32(HID,0x1c)) FN2(0xf6)((uint32_t)(uintptr_t)(HID+0x84),arm);
    else if(selected && iterations>=16u) post_hid();
}
uint32_t rc_control(uint32_t parameter,uint32_t length,const uint8_t *value) {
    RcState *s=state();
    uint32_t token,now;
    if(!s) return rc_original_control(parameter,length,value);
    if(parameter || length>1u || (length && !value)) return 2;
    token=lock(); now=now_locked(s);
    if(s->dispatch_active && (s->dispatch_epoch!=s->core.epoch || s->dispatch_expired)) { unlock(token); return 2; }
    if(length) {
        uint8_t copied=*value;
        /* The factory force-erase caller resets immediately after return.
         * It originally sends no HID neutral either: preserve its synchronous
         * terminate/erase ordering, while invalidating every pending report. */
        s->control_fenced=1; s->control_pending=0;
        s->bond_valid=0;
        sf_link(&s->core,0,0,now);
        unlock(token); native_control(1,copied); return 0;
    }
    /* Preserve the first valid request until it has been issued exactly once. */
    if(!s->control_pending) {
        s->control_pending=1; s->control_fenced=1;
        s->control_length=(uint8_t)length;
        s->control_value=length?*value:0;
        s->control_started=now;
        s->core.source_count=0; s->core.source_head=0; s->core.parser_count=0;
        sf_repair(&s->core,3,now);
    }
    unlock(token); post_hid(); return 0;
}
void rc_timer_callback(void) {
    RcState *s=state();
    uint32_t token;
    if(!s) { rc_original_timer(); return; }
    token=lock();
    s->clock_initialized=1;
    if(!HID[0x16]) {
        HID[0x16]=1;
        /* First native readiness callback is useful; retry callbacks must
         * leave their two-second backoff window and wait-event mask intact. */
        sf_wake(&s->core,now_locked(s));
    } else (void)now_locked(s);
    unlock(token);
    post_hid();
}
uint64_t rc_link_event(uint32_t role,uint32_t b,uint32_t c,uint32_t d) {
    uint64_t result=rc_original_link_event(role,b,c,d);
    RcState *s=state();
    if(s) { refresh(s,1,0); post_hid(); }
    return result;
}
uint64_t rc_attr_write(uint32_t conn,uintptr_t attr,const uint8_t *data,uint32_t length,uint32_t offset) {
    uint64_t result=rc_original_attr_write(conn,attr,data,length,offset);
    RcState *s=state();
    if(s && (uint32_t)result==0u) { refresh(s,1,0); post_hid(); }
    return result;
}
uint64_t rc_uart_receive(void) {
    RcState *s=state();
    uint8_t bytes[6];
    uint32_t token,count,wanted,partial,delivered,pos,released=0;
    if(!s) return rc_original_uart_receive();
    token=lock(); wanted=6u-s->core.parser_count; unlock(token);
    if(!wanted || wanted>6u) wanted=6u;
    count=FN3(0x756a)(get32(UART,0x10),(uint32_t)(uintptr_t)bytes,wanted);
    token=lock();
    if(count>wanted) { UART[7]=0; unlock(token); return 0; }
    partial=s->core.parser_count;
    if(count==wanted && partial<6u && (partial?s->core.parser[0]:bytes[0])==0xfeu) {
        uint8_t a=partial>2u?s->core.parser[2]:bytes[2u-partial];
        uint8_t b=partial>3u?s->core.parser[3]:bytes[3u-partial];
        if(a==0u || (a==1u && b==255u)) released=2u;
    }
#if RC_DIAGNOSTIC
    if(count && count<wanted) ++s->partial_reads;
#endif
    pos=(s->core.source_head+s->core.source_count)&15u;
    delivered=sf_uart_feed(&s->core,bytes,count);
    if(!delivered && s->core.source_barrier) s->handoff_mask|=(uint8_t)(released<<4);
    if(delivered) s->source_ticks[pos]=now_locked(s); /* At most one six-byte frame per bounded read. */
    partial=s->core.parser_count;
    if(count<wanted || !delivered) UART[7]=0; /* Native IRQ may post again. */
    if(count==wanted && !partial && !delivered) UART[0xb]=0;
    /* One more native APP read only after progress, to finish fragments that
     * are already in the driver's buffer. A zero read stops immediately. */
    if(count && partial) UART[4]|=1u;
    unlock(token);
    if(count) post_app();
    if(count && partial) {
        uint32_t sem=get32(APP,0x2c);
        if(sem) FN2(0x60)(sem,0x200);
    }
    return 0;
}
void rc_uart_close(void) {
    RcState *s=state();
    if(s) { uint32_t token=lock(); account_locked(s,now_locked(s)); s->core.parser_count=0; unlock(token); }
    rc_original_uart_close();
    if(s) { uint32_t token=lock(); account_locked(s,now_locked(s)); unlock(token); }
}
void rc_uart_worker(void) {
    RcState *s=state();
    uint8_t flags=UART[4];
    if(s) { uint32_t token=lock(); account_locked(s,now_locked(s)); unlock(token); }
    rc_original_uart_worker();
    if(s) {
        uint32_t token=lock();
        if(flags&4u) s->core.parser_count=0;
        account_locked(s,now_locked(s)); unlock(token);
    }
}
#if RC_DIAGNOSTIC
static void put16(uint8_t *to,uint32_t v) { to[0]=(uint8_t)v; to[1]=(uint8_t)(v>>8); }
static void put32(uint8_t *to,uint32_t v) { put16(to,v); put16(to+2,v>>16); }
static void diagnostic_render_locked(const uint8_t raw[10]) {
    uint8_t i;
    for(i=0;i<10;++i) {
        uint8_t a=raw[i]>>4,b=raw[i]&15;
        ((volatile uint8_t *)0x20000664u)[i*2]=(uint8_t)(a<10?a+'0':a-10+'A');
        ((volatile uint8_t *)0x20000664u)[i*2+1]=(uint8_t)(b<10?b+'0':b-10+'A');
    }
    ((volatile uint8_t *)0x20000664u)[20]=0;
}
/* Failure telemetry lives only in the existing 21-byte Hardware Revision
 * buffer. No latch or alternate RAM claim is introduced. Heap values
 * are the last existing sample; reasons8/9/10 precede release of the block. */
static void init_snapshot_locked(uint8_t reason,uint8_t bonds,uint32_t free_bytes,uint32_t largest,uint8_t deferred) {
    uint8_t raw[10];
    uint16_t app=get16(APP,0x20);
    raw[0]=0; raw[1]=0; raw[2]=reason; raw[3]=bonds;
    put16(raw+4,free_bytes); put16(raw+6,largest);
    raw[8]=(uint8_t)((get32(HID,0x1c)?1u:0u)|
        (HID[0x14]!=HID[0x15]?2u:0u)|(app&1u?4u:0u)|(app&0x10u?8u:0u)|(deferred?0x10u:0u));
    raw[9]=HID[0xd];
    diagnostic_render_locked(raw);
}
static void init_snapshot(uint8_t reason,uint8_t bonds,uint32_t free_bytes,uint32_t largest,uint8_t deferred) {
    uint32_t token=lock();
    init_snapshot_locked(reason,bonds,free_bytes,largest,deferred);
    unlock(token);
}
static void inactive_snapshot(void) {
    volatile const uint8_t *hw=(volatile const uint8_t *)0x20000664u;
    uint32_t token=lock();
    uint8_t i,valid=(uint8_t)(hw[0]=='0' && hw[1]=='0' && hw[2]=='0' && hw[3]=='0' &&
        hw[4]=='0' && ((hw[5]>='0' && hw[5]<='9') || hw[5]=='A' || hw[5]=='B') && !hw[20]);
    for(i=0;valid && i<20;++i)
        if(!((hw[i]>='0' && hw[i]<='9') || (hw[i]>='A' && hw[i]<='F'))) valid=0;
    if(valid && hw[5]=='0') {
        uint8_t unknown=1,legacy=1;
        for(i=6;i<16;++i) if(hw[i]!='F') unknown=0;
        for(i=0;i<20;++i) if(hw[i]!='0') legacy=0;
        valid=(uint8_t)(unknown || legacy);
    }
    /* GATT reads preserve the last admission record, including flags/role.
     * Invalid or formerly active contents carry no admission-failure provenance. */
    if(!valid) init_snapshot_locked(RC_INIT_UNKNOWN,255,65535,65535,0);
    unlock(token);
}
/* Three 20-character pages: page0 heap/drop/retry; page1 connection/UART ms;
 * page2 idlems, repairs, readiness. Offset>0 reuses the SAME rendered page. */
static void diagnostic_snapshot(RcState *s) {
    uint8_t raw[10],page=s?s->diag_page:0;
    uint32_t token,now=0;
    if(s) sample_heap(s);
    token=lock();
    clear(raw,10); raw[0]=page; raw[1]=(s!=0);
    if(s) {
        now=now_locked(s); account_locked(s,now);
        if(page==0) {
            put16(raw+2,s->minimum_free); put16(raw+4,s->core.dropped_source);
            put16(raw+6,s->core.dropped_tx); put16(raw+8,s->core.retries);
        } else if(page==1) { put32(raw+2,s->connected_ms); put32(raw+6,s->uart_ms); }
        else { put32(raw+2,s->idle_ms); raw[6]=(uint8_t)s->last_front_index; raw[7]=s->core.repair_mask;
               raw[8]=s->last_role; raw[9]=(uint8_t)((s->identity_verified?0x80u:0u)|
                   (s->last_front_index&0x100u?0x40u:0u)|(s->core.tx_count&31u)); }
        s->diag_page=(uint8_t)((page+1u)%3u);
    }
    diagnostic_render_locked(raw);
    unlock(token);
}
#endif
uint32_t rc_device_info_read(uint32_t conn,uintptr_t attr,uint8_t *out,uint16_t *length,uint16_t offset,uint8_t maxlen) {
#if RC_DIAGNOSTIC
    uint32_t uuidptr,uuid,n;
    if(ram_word((uint32_t)attr) && attr<=0x20004ff0u) {
        uuidptr=*(const uint32_t *)(attr+4);
        if(uuid_halfword(uuidptr)) {
            uuid=*(const uint16_t *)(uintptr_t)uuidptr;
            if(uuid==0x2a27u && *(const uint32_t *)(attr+12)==0x20000664u) {
                if(offset>20u) { *length=0; return 7; }
                RcState *s=state();
                if(!s) inactive_snapshot();
                else if(offset==0) diagnostic_snapshot(s);
                n=20u-offset; if(n>maxlen) n=maxlen;
                copy(out,(const uint8_t *)(uintptr_t)(0x20000664u+offset),n);
                *length=(uint16_t)n;
                return 0;
            }
        }
    }
#endif
    return rc_original_device_info(conn,attr,out,length,offset,maxlen);
}
