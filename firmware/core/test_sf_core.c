#include "sf_core.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static const uint8_t ZERO[8]={0};
static SfTxView next(SfCore *c,uint32_t now) {
    SfTxView v;
    assert(sf_tx_peek(c,now,&v));
    return v;
}
static void accepted(SfCore *c,SfTxView v,uint32_t now) {
    assert(sf_tx_complete(c,v.token,SF_SEND_ACCEPTED,now));
}
static void neutral(SfCore *c,uint32_t now) {
    SfTxView v=next(c,now);
    assert(memcmp(v.frame.data,ZERO,v.frame.len)==0);
    accepted(c,v,now);
}
static void ready(SfCore *c) {
    sf_core_init(c,0);
    sf_link(c,1,0x12345678,0);
    sf_cccd(c,3,0);
    neutral(c,0);
    neutral(c,0);
}
static void submit_consumer(SfCore *c,uint8_t key,uint32_t now) {
    uint8_t data[3]={key,0,0};
    assert(sf_submit(c,2,3,data,now)==SF_ADMITTED);
}
static void test_source_fifo_order_and_overflow_repair(void) {
    SfCore c;
    SfSourceEvent in={SF_SOURCE_ORIENTATION,5,{0,1,2,3,4},0},out;
    unsigned i;
    ready(&c);
    for(i=0;i<16;++i) { in.payload[0]=(uint8_t)i; assert(sf_source_push(&c,&in)); }
    for(i=0;i<16;++i) {
        assert(sf_source_pop(&c,&out));
        assert(out.kind==SF_SOURCE_ORIENTATION && out.count==5 && out.payload[0]==i);
    }
    assert(!sf_source_pop(&c,&out));
    for(i=0;i<16;++i) assert(sf_source_push(&c,&in));
    assert(!sf_source_push(&c,&in));
    assert(!sf_source_pop(&c,&out));
    assert(c.dropped_source==17 && c.quarantine_mask==3);
    neutral(&c,1);
    neutral(&c,1);
    assert(c.quarantine_mask==0);
    in.count=6;
    assert(!sf_source_push(&c,&in));
    assert(c.invalid==1);
}
static void test_uart_fragments_resynchronization_and_index_guard(void) {
    SfCore c;
    SfSourceEvent out;
    uint8_t frame[6]={0xfe,1,1,36,0xfe,0};
    uint8_t bad_then_partial[6]={0xfe,0,7,0xfe,0,1};
    uint8_t tail[3]={24,0,0};
    uint8_t bad_index[6]={0xfe,0,1,45,0,0};
    unsigned i;
    ready(&c);
    assert(!sf_uart_feed(&c,frame,2));
    assert(sf_uart_feed(&c,frame+2,4)==1);
    assert(sf_source_pop(&c,&out) && out.kind==SF_SOURCE_UART && out.count==5);
    assert(out.payload[0]==1 && out.payload[1]==1 && out.payload[2]==36 && out.payload[3]==0xfe);
    assert(!sf_uart_feed(&c,bad_then_partial,6));
    assert(sf_uart_feed(&c,tail,3)==1);
    assert(sf_source_pop(&c,&out) && out.payload[2]==24);
    assert(!sf_uart_feed(&c,bad_index,6));
    assert(sf_uart_feed(&c,frame,6)==1);
    assert(sf_source_pop(&c,&out) && out.payload[2]==36);
    for(i=0;i<256;++i) assert(sf_front_index_valid(&c,(uint8_t)i)==(i<45 || i==255));
    assert(c.invalid==2);
}
static void test_order_single_worker_and_accepted_power_never_replays(void) {
    SfCore c;
    SfTxView a,b;
    ready(&c);
    submit_consumer(&c,0x30,1);
    submit_consumer(&c,0,2);
    a=next(&c,2);
    assert(a.frame.data[0]==0x30 && a.frame.id==2);
    assert(!sf_tx_peek(&c,2,&b));
    assert(!sf_tx_complete(&c,a.token+1,SF_SEND_ACCEPTED,2));
    accepted(&c,a,2);
    assert(!sf_tx_complete(&c,a.token,SF_SEND_RETRYABLE,2));
    assert(c.release_mask==2);
    b=next(&c,2);
    assert(b.frame.data[0]==0);
    accepted(&c,b,2);
    sf_wake(&c,3000);
    assert(!sf_tx_peek(&c,3000,&b) && !c.release_mask);
}
static void test_full_queue_rejects_new_press_without_committing_cache(void) {
    SfCore c;
    SfTxView v;
    uint8_t data[8]={0};
    unsigned i;
    ready(&c);
    for(i=0;i<16;++i) { data[2]=(uint8_t)(4+i); assert(sf_submit(&c,1,8,data,1)==SF_ADMITTED); }
    data[2]=90;
    assert(sf_submit(&c,1,8,data,1)==SF_FULL);
    assert(c.dropped_tx==1 && c.tx_count==16);
    for(i=0;i<16;++i) {
        v=next(&c,2);
        assert(v.frame.data[2]==4+i);
        accepted(&c,v,2);
    }
    assert(sf_submit(&c,1,8,data,2)==SF_ADMITTED);
    v=next(&c,2);
    assert(v.frame.data[2]==90);
}
static void test_saturation_preserves_consumer_release_among_keyboard_reports(void) {
    SfCore c;
    SfTxView v;
    uint8_t data[8]={0};
    uint8_t right[3]={0x45,0,0};
    unsigned i;
    ready(&c);
    submit_consumer(&c,0x45,1);
    v=next(&c,1); accepted(&c,v,1);
    for(i=0;i<16;++i) { data[2]=(uint8_t)(4+i); assert(sf_submit(&c,1,8,data,2)==SF_ADMITTED); }
    assert(sf_submit(&c,2,3,ZERO,3)==SF_ADMITTED);
    assert(sf_submit(&c,2,3,right,3)==SF_QUARANTINED);
    v=next(&c,3);
    assert(v.frame.id==2 && memcmp(v.frame.data,ZERO,3)==0);
    accepted(&c,v,3);
    assert(!(c.release_mask&2) && !(c.quarantine_mask&2));
    for(i=0;i<16;++i) {
        v=next(&c,3);
        assert(v.frame.id==1 && v.frame.data[2]==4+i);
        accepted(&c,v,3);
    }
    assert(!sf_tx_peek(&c,3,&v));
}
static void test_expired_presses_drop_but_release_obligations_do_not_expire(void) {
    SfCore c;
    SfTxView v;
    ready(&c);
    submit_consumer(&c,0x45,10);
    submit_consumer(&c,0,11);
    v=next(&c,2010);
    assert(c.expired==1 && v.frame.data[0]==0);
    accepted(&c,v,2010);
    submit_consumer(&c,0x45,2100);
    v=next(&c,2100); accepted(&c,v,2100);
    submit_consumer(&c,0,2101);
    v=next(&c,9000);
    assert(v.frame.data[0]==0 && c.release_mask==2);
    accepted(&c,v,9000);
    assert(!c.release_mask);
}
static void test_transient_backoff_and_release_recovery_after_event(void) {
    SfCore c;
    SfTxView v;
    uint32_t t=101;
    uint32_t delays[5]={20,50,100,200,200};
    unsigned i;
    ready(&c);
    submit_consumer(&c,0x45,100);
    v=next(&c,100); accepted(&c,v,100);
    submit_consumer(&c,0,101);
    for(i=0;i<5;++i) {
        v=next(&c,t);
        assert(sf_tx_complete(&c,v.token,SF_SEND_RETRYABLE,t));
        assert(c.release_mask==2 && c.retry_due==t+delays[i]);
        assert(!sf_tx_peek(&c,t+delays[i]-1,&v));
        t+=delays[i];
    }
    v=next(&c,2101);
    assert(sf_tx_complete(&c,v.token,SF_SEND_RETRYABLE,2101));
    assert(c.wait_event && (c.repair_mask&2) && (c.release_mask&2));
    assert(!sf_tx_peek(&c,50000,&v));
    sf_wake(&c,50001);
    v=next(&c,50001);
    assert(v.frame.id==2 && v.frame.data[0]==0);
    accepted(&c,v,50001);
    assert(!c.release_mask && !c.quarantine_mask);
}
static void test_unavailable_waits_for_useful_event_without_pop(void) {
    SfCore c;
    SfTxView v;
    ready(&c);
    submit_consumer(&c,0x45,1);
    v=next(&c,1);
    assert(sf_tx_complete(&c,v.token,SF_SEND_UNAVAILABLE,1));
    assert(c.tx_count==1 && !c.release_mask);
    assert(!sf_tx_peek(&c,100,&v));
    sf_wake(&c,101);
    v=next(&c,101);
    assert(v.frame.data[0]==0x45);
    accepted(&c,v,101);
    assert(c.release_mask==2 && c.tx_count==0);
}
static void test_connection_epoch_peer_and_stale_completion(void) {
    SfCore c;
    SfTxView old,v;
    uint16_t epoch;
    uint8_t key[3]={0x45,0,0};
    sf_core_init(&c,0);
    assert(sf_submit(&c,2,3,key,0)==SF_NO_PEER);
    ready(&c);
    submit_consumer(&c,0x45,1);
    old=next(&c,1);
    epoch=c.epoch;
    sf_link(&c,0,0x12345678,2);
    assert(c.epoch!=epoch && !c.tx_count && !c.release_mask);
    assert(!sf_tx_complete(&c,old.token,SF_SEND_ACCEPTED,3));
    submit_consumer(&c,0x44,3);
    sf_link(&c,1,0x12345678,4);
    sf_cccd(&c,3,4);
    neutral(&c,4); neutral(&c,4);
    v=next(&c,4);
    assert(v.frame.data[0]==0x44);
    accepted(&c,v,4);
    submit_consumer(&c,0x43,5);
    sf_link(&c,1,0x22222222,6);
    sf_cccd(&c,3,6);
    neutral(&c,6); neutral(&c,6);
    assert(!sf_tx_peek(&c,6,&v));
}
static void test_cccd_and_protocol_changes_neutralize_without_old_replay(void) {
    SfCore c;
    SfTxView v;
    uint8_t right[3]={0x45,0,0};
    ready(&c);
    submit_consumer(&c,0x45,1);
    sf_cccd(&c,1,2);
    assert(!sf_tx_peek(&c,2,&v));
    assert(sf_submit(&c,2,3,right,3)==SF_QUARANTINED);
    sf_cccd(&c,3,4);
    neutral(&c,4);
    assert(!sf_tx_peek(&c,4,&v));
    assert(sf_submit(&c,2,3,right,4)==SF_ADMITTED);
    sf_protocol(&c,0,5);
    neutral(&c,5);
    assert(!sf_tx_peek(&c,5,&v));
    sf_protocol(&c,1,6);
    neutral(&c,6); neutral(&c,6);
    assert(!sf_tx_peek(&c,6,&v));
    sf_protocol(&c,9,7);
    assert(c.protocol==1 && c.invalid==1);
}
static void test_keyboard_compares_all_eight_bytes_and_validates_lengths(void) {
    SfCore c;
    SfTxView v;
    uint8_t a[8]={0,0,4,5,6,0,0,0},b[8]={0,0,4,5,7,0,0,0};
    ready(&c);
    assert(sf_core_size(&c)<=640);
    assert(sf_submit(&c,1,8,a,1)==SF_ADMITTED);
    assert(sf_submit(&c,1,8,b,2)==SF_ADMITTED);
    assert(sf_submit(&c,1,8,b,2)==SF_DUPLICATE);
    v=next(&c,2); assert(v.frame.data[4]==6); accepted(&c,v,2);
    v=next(&c,2); assert(v.frame.data[4]==7); accepted(&c,v,2);
    assert(sf_submit(&c,1,7,a,2)==SF_INVALID);
    assert(sf_submit(&c,2,8,a,2)==SF_INVALID);
    assert(sf_submit(&c,3,3,a,2)==SF_INVALID);
    assert(sf_submit(&c,1,8,0,2)==SF_INVALID);
    assert(c.invalid==4);
}
static void test_overflow_during_inflight_press_repairs_after_acceptance(void) {
    SfCore c;
    SfTxView v;
    ready(&c);
    submit_consumer(&c,0x45,1);
    v=next(&c,1);
    sf_repair(&c,2,1);
    accepted(&c,v,1);
    assert(c.release_mask==2);
    v=next(&c,1);
    assert(v.frame.id==2 && v.frame.data[0]==0);
    accepted(&c,v,1);
    assert(!c.release_mask && !c.quarantine_mask && !c.tx_count);
}
static void test_unavailable_report_does_not_block_other_report(void) {
    SfCore c;
    SfTxView v;
    uint8_t key[8]={0,0,4,0,0,0,0,0};
    ready(&c);
    submit_consumer(&c,0x45,1);
    assert(sf_submit(&c,1,8,key,1)==SF_ADMITTED);
    v=next(&c,1);
    assert(sf_tx_complete(&c,v.token,SF_SEND_UNAVAILABLE,1));
    /* No useful event woke consumer2; a queued keyboard frame remains usable. */
    v=next(&c,2);
    assert(v.frame.id==1 && v.frame.data[2]==4);
    accepted(&c,v,2);
    assert(!sf_tx_peek(&c,2,&v) && c.tx_count==1 && c.wait_event==2);
    sf_wake(&c,3);
    v=next(&c,3);
    assert(v.frame.id==2 && v.frame.data[0]==0x45);
}
static void test_expired_offline_press_does_not_suppress_fresh_press(void) {
    SfCore c;
    SfTxView v;
    uint8_t key[3]={0x45,0,0};
    sf_core_init(&c,0);
    sf_link(&c,0,0x12345678,0);
    assert(sf_submit(&c,2,3,key,1)==SF_ADMITTED);
    assert(sf_submit(&c,2,3,key,2001)==SF_ADMITTED);
    assert(c.expired==1 && c.tx_count==1);
    sf_link(&c,1,0x12345678,2002);
    sf_cccd(&c,3,2002);
    neutral(&c,2002); neutral(&c,2002);
    v=next(&c,2002);
    assert(v.frame.data[0]==0x45 && v.frame.tick==2001);
}
int main(void) {
#define RUN(name) do { name(); puts(#name " PASS"); } while(0)
    RUN(test_source_fifo_order_and_overflow_repair);
    RUN(test_uart_fragments_resynchronization_and_index_guard);
    RUN(test_order_single_worker_and_accepted_power_never_replays);
    RUN(test_full_queue_rejects_new_press_without_committing_cache);
    RUN(test_saturation_preserves_consumer_release_among_keyboard_reports);
    RUN(test_expired_presses_drop_but_release_obligations_do_not_expire);
    RUN(test_transient_backoff_and_release_recovery_after_event);
    RUN(test_unavailable_waits_for_useful_event_without_pop);
    RUN(test_connection_epoch_peer_and_stale_completion);
    RUN(test_cccd_and_protocol_changes_neutralize_without_old_replay);
    RUN(test_keyboard_compares_all_eight_bytes_and_validates_lengths);
    RUN(test_overflow_during_inflight_press_repairs_after_acceptance);
    RUN(test_unavailable_report_does_not_block_other_report);
    RUN(test_expired_offline_press_does_not_suppress_fresh_press);
    printf("14/14 passed; runtime=%zu bytes\n",sizeof(SfCore));
    return 0;
}
