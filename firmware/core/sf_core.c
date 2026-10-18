#include "sf_core.h"

static void bytes_zero(uint8_t *p, uint32_t n) { while(n--) *p++=0; }
static void bytes_copy(uint8_t *to, const uint8_t *from, uint32_t n) {
    while(n--) *to++=*from++;
}
static int bytes_equal(const uint8_t *a,const uint8_t *b,uint8_t n) {
    while(n--) if(*a++!=*b++) return 0;
    return 1;
}
static uint8_t bit_for(uint8_t id) { return (uint8_t)(1u<<(id-1u)); }
static uint8_t report_len(uint8_t id) { return id==1u ? 8u : 3u; }
static int is_zero(const uint8_t *data,uint8_t len) {
    while(len--) if(*data++) return 0;
    return 1;
}
static int due(uint32_t now,uint32_t deadline) {
    return (int32_t)(now-deadline)>=0;
}
static uint8_t next_index(uint8_t index) { return (uint8_t)((index+1u)&15u); }
static void cancel_flight(SfCore *c) {
    c->flight_id=0;
    c->retry_active=0;
    c->retry_step=0;
    c->wait_event=0;
    ++c->token;
    if(!c->token) ++c->token;
}
static void compact_tx(SfCore *c) {
    uint8_t read,write=0,src,dst;
    if(c->flight_id) return;
    for(read=0;read<c->tx_count;++read) {
        src=(uint8_t)((c->tx_head+read)&15u);
        if(!c->tx[src].id || c->tx[src].epoch!=c->epoch) continue;
        dst=(uint8_t)((c->tx_head+write)&15u);
        if(src!=dst) bytes_copy((uint8_t *)&c->tx[dst],(const uint8_t *)&c->tx[src],sizeof(SfTx));
        ++write;
    }
    c->tx_count=write;
}
static void expire_pending(SfCore *c,uint32_t now) {
    uint8_t i,pos,bit;
    for(i=0;i<c->tx_count;++i) {
        pos=(uint8_t)((c->tx_head+i)&15u);
        if(!c->tx[pos].id || (c->flight_id && !c->flight_repair && pos==c->flight_pos)) continue;
        if(is_zero(c->tx[pos].data,c->tx[pos].len)) continue;
        if((uint32_t)(now-c->tx[pos].tick)<SF_PRESS_TTL_MS) continue;
        bit=bit_for(c->tx[pos].id);
        c->admitted_mask=(uint8_t)(c->admitted_mask & ~bit);
        c->tx[pos].id=0;
        ++c->expired;
    }
    compact_tx(c);
}
static void invalidate_report(SfCore *c,uint8_t id) {
    uint8_t i,pos=c->tx_head;
    for(i=0;i<c->tx_count;++i) {
        if(c->tx[pos].id==id) c->tx[pos].id=0;
        pos=next_index(pos);
    }
    c->admitted_mask=(uint8_t)(c->admitted_mask & ~bit_for(id));
}
static void repair(SfCore *c,uint8_t mask) {
    uint8_t id;
    for(id=1;id<=2;++id) if(mask & bit_for(id)) invalidate_report(c,id);
    c->repair_mask=(uint8_t)(c->repair_mask|mask);
    c->quarantine_mask=(uint8_t)(c->quarantine_mask|mask);
}
static void reset_session(SfCore *c,uint32_t now) {
    ++c->epoch;
    c->source_head=0;
    c->source_count=0;
    c->source_barrier=0;
    c->parser_count=0;
    c->tx_head=0;
    c->tx_count=0;
    c->cccd=0;
    c->protocol=1;
    c->repair_mask=3;
    c->quarantine_mask=0;
    c->release_mask=0;
    c->admitted_mask=0;
    bytes_zero(&c->admitted[0][0],16);
    bytes_zero(&c->accepted[0][0],16);
    cancel_flight(c);
    c->retry_started=now;
    c->retry_due=now;
}
void sf_core_init(SfCore *c,uint32_t now) {
    bytes_zero((uint8_t *)c,(uint32_t)sizeof(*c));
    c->protocol=1;
    c->epoch=1;
    c->token=1;
    c->retry_started=now;
    c->retry_due=now;
}
uint32_t sf_core_size(SfCore *c) { (void)c; return (uint32_t)sizeof(SfCore); }
int sf_source_push(SfCore *c,const SfSourceEvent *event) {
    uint8_t pos;
    if(!event || !event->kind || event->kind>SF_SOURCE_ORIENTATION || event->count>5u) {
        ++c->invalid;
        return 0;
    }
    if(c->source_count==SF_FIFO_CAPACITY || c->source_barrier) {
        ++c->dropped_source;
        c->source_barrier=1;
        repair(c,3);
        return 0;
    }
    pos=(uint8_t)((c->source_head+c->source_count)&15u);
    bytes_copy((uint8_t *)&c->source[pos],(const uint8_t *)event,sizeof(*event));
    ++c->source_count;
    return 1;
}
int sf_source_pop(SfCore *c,SfSourceEvent *event) {
    if(c->source_barrier) {
        c->dropped_source+=c->source_count;
        c->source_count=0;
        c->source_head=0;
        c->source_barrier=0;
        return 0;
    }
    if(!event || !c->source_count) return 0;
    bytes_copy((uint8_t *)event,(const uint8_t *)&c->source[c->source_head],sizeof(*event));
    c->source_head=next_index(c->source_head);
    --c->source_count;
    return 1;
}
int sf_front_index_valid(SfCore *c,uint8_t index) {
    (void)c;
    return index<45u || index==255u;
}
static int valid_uart(SfCore *c) {
    uint8_t kind=c->parser[2];
    if(kind==1u) return sf_front_index_valid(c,c->parser[3]);
    return kind==0u || kind==2u || kind==0xfau || kind==0xfbu || kind==0xffu;
}
uint32_t sf_uart_feed(SfCore *c,const uint8_t *data,uint32_t len) {
    uint32_t delivered=0;
    uint8_t i,j;
    SfSourceEvent event;
    if(!data) return 0;
    while(len--) {
        uint8_t b=*data++;
        if(!c->parser_count && b!=0xfeu) continue;
        c->parser[c->parser_count++]=b;
        if(c->parser_count!=6u) continue;
        if(valid_uart(c)) {
            event.kind=SF_SOURCE_UART;
            event.count=5;
            event.reserved=0;
            bytes_copy(event.payload,c->parser+1,5);
            delivered+=(uint32_t)sf_source_push(c,&event);
            c->parser_count=0;
        } else {
            ++c->invalid;
            /* Shift a possible following FE header; retain its partial body. */
            i=1;
            while(i<6u && c->parser[i]!=0xfeu) ++i;
            j=0;
            while(i<6u) c->parser[j++]=c->parser[i++];
            c->parser_count=j;
        }
    }
    return delivered;
}
void sf_link(SfCore *c,uint8_t connected,uint32_t peer,uint32_t now) {
    connected=(uint8_t)(connected!=0);
    if(peer!=c->peer || (c->connected && !connected)) reset_session(c,now);
    c->peer=peer;
    c->connected=(uint8_t)(connected && peer!=0u);
    if(c->connected) sf_wake(c,now);
}
void sf_cccd(SfCore *c,uint8_t mask,uint32_t now) {
    uint8_t disabled,enabled;
    mask=(uint8_t)(mask&3u);
    disabled=(uint8_t)(c->cccd & ~mask);
    enabled=(uint8_t)(mask & ~c->cccd);
    if(disabled) repair(c,disabled);
    if(enabled) c->repair_mask=(uint8_t)(c->repair_mask|enabled);
    c->cccd=mask;
    if(disabled && c->flight_id && (disabled & bit_for(c->flight_id))) cancel_flight(c);
    sf_wake(c,now);
}
void sf_protocol(SfCore *c,uint8_t mode,uint32_t now) {
    if(mode>1u) { ++c->invalid; return; }
    if(mode==c->protocol) return;
    repair(c,3);
    c->protocol=mode;
    cancel_flight(c);
    sf_wake(c,now);
}
void sf_wake(SfCore *c,uint32_t now) {
    if(c->wait_event) {
        c->wait_event=0;
        c->retry_active=0;
        c->retry_step=0;
        c->retry_due=now;
    }
}
void sf_repair(SfCore *c,uint8_t mask,uint32_t now) {
    repair(c,(uint8_t)(mask&3u));
    sf_wake(c,now);
}
enum SfSubmit sf_submit(SfCore *c,uint8_t id,uint8_t len,const uint8_t *data,uint32_t now) {
    uint8_t bit,pos,zero;
    SfTx *frame;
    if(id<1u || id>2u || len!=report_len(id) || !data) {
        ++c->invalid;
        return SF_INVALID;
    }
    if(!c->peer) return SF_NO_PEER;
    bit=bit_for(id);
    zero=(uint8_t)is_zero(data,len);
    sf_wake(c,now);
    expire_pending(c,now);
    if(c->quarantine_mask & bit) {
        if(zero) {
            c->repair_mask=(uint8_t)(c->repair_mask|bit);
            return SF_ADMITTED;
        }
        ++c->dropped_tx;
        return SF_QUARANTINED;
    }
    if((c->admitted_mask & bit) && bytes_equal(c->admitted[id-1],data,len)) return SF_DUPLICATE;
    if(c->tx_count==SF_FIFO_CAPACITY) {
        ++c->dropped_tx;
        if(!zero) return SF_FULL;
        repair(c,bit);
        bytes_zero(c->admitted[id-1],8);
        c->admitted_mask=(uint8_t)(c->admitted_mask|bit);
        return SF_ADMITTED;
    }
    pos=(uint8_t)((c->tx_head+c->tx_count)&15u);
    frame=&c->tx[pos];
    frame->tick=now;
    frame->epoch=c->epoch;
    frame->id=id;
    frame->len=len;
    bytes_zero(frame->data,8);
    bytes_copy(frame->data,data,len);
    ++c->tx_count;
    bytes_zero(c->admitted[id-1],8);
    bytes_copy(c->admitted[id-1],data,len);
    c->admitted_mask=(uint8_t)(c->admitted_mask|bit);
    return SF_ADMITTED;
}
static uint8_t available(SfCore *c) {
    if(!c->connected || !c->peer) return 0;
    return (uint8_t)(c->cccd & (c->protocol ? 3u : 1u));
}
static void make_flight(SfCore *c,const SfTx *frame,uint8_t repair_frame,uint8_t pos,uint32_t now,SfTxView *out) {
    ++c->token;
    if(!c->token) ++c->token;
    c->flight_id=frame->id;
    c->flight_len=frame->len;
    c->flight_repair=repair_frame;
    c->flight_pos=pos;
    bytes_copy(c->flight_data,frame->data,8);
    bytes_copy((uint8_t *)&out->frame,(const uint8_t *)frame,sizeof(*frame));
    out->token=c->token;
    if(!c->retry_active) c->retry_started=now;
}
uint32_t sf_tx_peek(SfCore *c,uint32_t now,SfTxView *out) {
    uint8_t mask,id,bit,i,pos;
    SfTx neutral;
    if(!out || c->flight_id) return 0;
    expire_pending(c,now);
    if(c->retry_active && !due(now,c->retry_due)) return 0;
    mask=(uint8_t)(available(c) & ~c->wait_event);
    for(id=1;id<=2;++id) {
        bit=bit_for(id);
        if(c->repair_mask & mask & bit) {
            neutral.tick=now;
            neutral.epoch=c->epoch;
            neutral.id=id;
            neutral.len=report_len(id);
            bytes_zero(neutral.data,8);
            make_flight(c,&neutral,1,0,now,out);
            return out->token;
        }
    }
    for(i=0;i<c->tx_count;++i) {
        SfTx *frame;
        pos=(uint8_t)((c->tx_head+i)&15u);
        frame=&c->tx[pos];
        if(!frame->id || frame->epoch!=c->epoch) { frame->id=0; continue; }
        bit=bit_for(frame->id);
        if(c->quarantine_mask & bit) { frame->id=0; continue; }
        if(!is_zero(frame->data,frame->len) && (uint32_t)(now-frame->tick)>=SF_PRESS_TTL_MS) {
            c->admitted_mask=(uint8_t)(c->admitted_mask & ~bit);
            ++c->expired;
            frame->id=0;
            continue;
        }
        if(!(mask & bit)) continue;
        make_flight(c,frame,0,pos,now,out);
        return out->token;
    }
    compact_tx(c);
    return 0;
}
int sf_tx_complete(SfCore *c,uint32_t token,enum SfSendResult result,uint32_t now) {
    uint8_t id,bit,zero,repair_frame;
    uint32_t delay;
    if(!c->flight_id || token!=c->token) return 0;
    if(result!=SF_SEND_ACCEPTED && result!=SF_SEND_RETRYABLE && result!=SF_SEND_UNAVAILABLE) {
        ++c->invalid;
        result=SF_SEND_UNAVAILABLE;
    }
    id=c->flight_id;
    bit=bit_for(id);
    zero=(uint8_t)is_zero(c->flight_data,c->flight_len);
    repair_frame=c->flight_repair;
    c->flight_id=0;
    if(result==SF_SEND_ACCEPTED) {
        bytes_copy(c->accepted[id-1],c->flight_data,8);
        if(zero) c->release_mask=(uint8_t)(c->release_mask & ~bit);
        else c->release_mask=(uint8_t)(c->release_mask|bit);
        if(repair_frame) {
            c->repair_mask=(uint8_t)(c->repair_mask & ~bit);
            c->quarantine_mask=(uint8_t)(c->quarantine_mask & ~bit);
            c->admitted_mask=(uint8_t)(c->admitted_mask & ~bit);
        } else c->tx[c->flight_pos].id=0;
        compact_tx(c);
        c->retry_active=0;
        c->retry_step=0;
        c->wait_event=(uint8_t)(c->wait_event & ~bit);
        return 1;
    }
    if(!repair_frame && (c->quarantine_mask & bit)) {
        c->tx[c->flight_pos].id=0;
        compact_tx(c);
        c->retry_active=0;
        c->retry_step=0;
        return 1;
    }
    if(result==SF_SEND_UNAVAILABLE) {
        c->wait_event=(uint8_t)(c->wait_event|bit);
        c->retry_active=0;
        return 1;
    }
    ++c->retries;
    if((uint32_t)(now-c->retry_started)>=SF_PRESS_TTL_MS) {
        if(zero || (c->release_mask & bit)) repair(c,bit);
        if(!repair_frame) c->tx[c->flight_pos].id=0;
        compact_tx(c);
        c->retry_active=0;
        c->wait_event=(uint8_t)(c->wait_event|bit);
        return 1;
    }
    delay=c->retry_step==0u ? 20u : c->retry_step==1u ? 50u : c->retry_step==2u ? 100u : 200u;
    if(c->retry_step<3u) ++c->retry_step;
    c->retry_due=now+delay;
    c->retry_active=1;
    return 1;
}
