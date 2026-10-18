/* Thumb-2 native ABI bridges for the hash-pinned GVK1EH 06.05 image.
 * Every overwritten instruction window is listed in hooks.json. Native
 * PC-relative loads are reconstructed with their resolved literal values;
 * instruction bytes are never copied to a new PC. Absolute resumes use
 * LDR PC and odd Thumb addresses, preserving all other registers and flags.
 */
.syntax unified
.cpu cortex-m3
.thumb

.macro FN name
    .section .text.\name,"ax",%progbits
    .balign 4
    .global \name
    .type \name,%function
    .thumb_func
\name:
.endm
.macro END name
    .size \name,.-\name
    .ltorg
.endm
.macro RESUME address
    ldr.w pc, .Lresume_\@
    .balign 4
.Lresume_\@:
    .word (\address + 1)
.endm
.macro SAVE_VOLATILES_FLAGS
    push {r0,r1,r2,r3,r12,lr}
    mrs r0,apsr
    push {r0,r1}             /* flags + alignment; C-call SP remains 8-aligned */
.endm
.macro RESTORE_VOLATILES_FLAGS
    pop {r0,r1}
    msr apsr_nzcvq,r0
    pop {r0,r1,r2,r3,r12,lr}
.endm

/* Rear callback(count,data). Reproduce CMP's flags and MOV before native BNE. */
FN rc_original_rear
    cmp r0,#255
    mov r2,r0
    RESUME 0x1a94
END rc_original_rear

/* Front callback(count,data,special): six-byte overwritten prologue. */
FN rc_original_front
    push {r3,r4,r5,lr}
    ldr r4,=0x20000928
    RESUME 0x1ac2
END rc_original_front

/* Native event drain preserves its original 32-byte frame and local slots. */
FN rc_original_event_drain
    push {r1,r2,r3,r4,r5,r6,r7,lr}
    ldr r4,=0x20000928
    RESUME 0x187e
END rc_original_event_drain

/* Continue after the two legacy source-mailbox branches, with the remaining
 * mask supplied in R0. Native code returns through its own original epilogue.
 */
FN rc_native_event_rest
    push {r1,r2,r3,r4,r5,r6,r7,lr}
    ldr r4,=0x20000928
    mov r5,r0
    RESUME 0x189e
END rc_native_event_rest

FN rc_original_consumer
    ldr r1,=0x20003044
    RESUME 0x21e0
END rc_original_consumer

FN rc_original_keyboard
    push {r2,r3,r4,r5,r6,lr}
    mov r5,r1
    RESUME 0x2174
END rc_original_keyboard

FN rc_original_hid_submit
    push {r3,r4,r5,r6,r7,lr}
    mov r4,r2
    RESUME 0x4892
END rc_original_hid_submit

/* HidDev_SetParameter(paramID,length,value): original eight-register frame. */
FN rc_original_control
    push {r3,r4,r5,r6,r7,r8,r9,lr}
    RESUME 0x48f8
END rc_original_control

FN rc_original_link_event
    push {r2,r3,r4,r5,r6,r7,r8,lr}
    RESUME 0x4d26
END rc_original_link_event

/* HID main calls4C2A at480A. Its live message is freed by the caller; the
 * dispatcher frees nested payloads itself. Rebuild its complete4-byte prefix. */
FN rc_original_hid_message
    push {r2,r3,r4,r5,r6,lr}
    mov r6,r0
    RESUME 0x4c2e
END rc_original_hid_message

/* APP task's consumed Event mask is live in callee-savedR5 at1796. Native
 *2AE6 takes no arguments. This bridge adds no retained stack frame. */
FN rc_app_turn_bridge
    mov r0,r5
    b.w rc_app_turn
END rc_app_turn_bridge

/* Only the real rear source call188C carries a useful release proof.
 * R5 is the mailbox mask captured before native1878 clears APP+20. */
FN rc_rear_source_bridge
    mov r2,r5
    b.w rc_rear_source_decode
END rc_rear_source_bridge

/* Fifth argument remains at entry-SP, then native-SP+40 after the push. */
FN rc_original_attr_write
    push {r1,r2,r3,r4,r5,r6,r7,r8,r9,lr}
    RESUME 0x4ab4
END rc_original_attr_write

FN rc_original_uart_receive
    push {r2,r3,r4,r5,r7,lr}
    ldr r4,=0x20000dd0
    RESUME 0x551e
END rc_original_uart_receive

FN rc_original_uart_close
    push {r4,lr}
    ldr r4,=0x20000dd0
    RESUME 0x53a8
END rc_original_uart_close

FN rc_original_uart_worker
    push {r3,r4,r5,r6,r7,lr}
    ldr r4,=0x20000dd0
    RESUME 0x564c
END rc_original_uart_worker

/* The parser's first two saved words are its original six-byte local frame.
 * Its native epilogue intentionally pops them into R0/R1, not R2/R3.
 */
FN rc_native_uart_frame
    push {r2,r3,r4,r5,r7,lr}
    /* Byte pointer has no C alignment guarantee; do not issue word loads. */
    .irp byte,0,1,2,3,4,5
        ldrb r1,[r0,#\byte]
        strb r1,[sp,#\byte]
    .endr
    ldr r4,=0x20000dd0
    RESUME 0x552c
END rc_native_uart_frame

FN rc_original_timer
    ldr r0,=0x20000ad8
    movs r1,#1
    RESUME 0x50bc
END rc_original_timer

/* Six-argument GATT read callback. The original 48-byte prologue keeps the
 * offset/max-length arguments at native SP+0x30 and SP+0x34 respectively.
 * Fourth argument is a uint16_t output-length pointer (native STRH writes).
 */
FN rc_original_device_info
    push {r0,r1,r2,r3,r4,r5,r6,r7,r8,r10,r11,lr}
    RESUME 0x5254
END rc_original_device_info

/* Replace 0x1d2a..0x1d2f. Ordinary front usages reach the admission queue
 * before HID readiness only while the adapter is active. Voice usage 0x221
 * and its release retain the stock readiness/pending-voice branches.
 * Inactive means the already verified 06.07 behavior (ordinary keys still
 * honor the native readiness check); no queue marker is touched here.
 */
FN rc_front_gate
    SAVE_VOLATILES_FLAGS
    bl rc_enabled
    cbz r0,.Lfront_inactive
    RESTORE_VOLATILES_FLAGS
    cmp r4,r8
    beq .Lfront_readiness
    cmp r1,r8
    bne .Lfront_ordinary
    cmp r4,#0
    beq .Lfront_readiness
.Lfront_ordinary:
    RESUME 0x1d30
.Lfront_inactive:
    RESTORE_VOLATILES_FLAGS
.Lfront_readiness:
    ldrb r0,[r5,#0x12]
    cmp r0,#5
    bne .Lfront_not_ready
    RESUME 0x1d30
.Lfront_not_ready:
    RESUME 0x1d58
END rc_front_gate

/* Inline hook in the native HID task. Bit mask 0x04 (R5 bit index 2) is
 * selected by original LSLS #29. Preserve live volatile registers, LR and
 * APSR across C. If allocation/identity initialization failed, execute the
 * exact original LSLS/BPL semantics, then continue its native drain body.
 */
FN rc_hid_drain
    SAVE_VOLATILES_FLAGS
    bl rc_enabled
    cbz r0,.Ldrain_inactive
    lsls r0,r5,#29
    bpl .Ldrain_done
    bl rc_hid_worker
.Ldrain_done:
    RESTORE_VOLATILES_FLAGS
    RESUME 0x47aa
.Ldrain_inactive:
    RESTORE_VOLATILES_FLAGS
    lsls r1,r5,#29
    bpl .Ldrain_native_skip
    RESUME 0x4770
.Ldrain_native_skip:
    RESUME 0x47aa
END rc_hid_drain

/* Replaces only the BL5006 at4784. Native488E bounds length to0..9;
 * each of the three aligned slots is header3+payload9 =12 bytes. Before
 * publishing the new read index, copy that entire slot onto the HID stack.
 * The only frame retained by4EF4/RPC is these16 bytes, not a C call frame.
 * APP owns admission and native producers; a suspended HID send therefore
 * retains no pointer into the36 bytes which APP may subsequently claim.
 */
FN rc_native_legacy_snapshot
    sub sp,#16
    ldr r12,=0x2bab
    blx r12
    str r0,[sp,#12]          /* native gate token; last word is not payload */
    ldr r0,[r7]
    ldr r1,=0x53465243
    cmp r0,r1
    beq .Llegacy_no_slot
    ldrb r0,[r6,#0x14]      /* re-read both indexes inside the gate */
    ldrb r1,[r6,#0x15]
    cmp r0,r1
    beq .Llegacy_no_slot
    cmp r0,#3
    bhs .Llegacy_no_slot
    cmp r1,#3
    bhs .Llegacy_no_slot
    adds r0,r0,#1
    cmp r0,#3
    it eq
    moveq r0,#0
    add.w r1,r0,r0,lsl #1
    add.w r1,r7,r1,lsl #2
    ldr r2,[r1]
    str r2,[sp]
    ldr r2,[r1,#4]
    str r2,[sp,#4]
    ldr r2,[r1,#8]
    str r2,[sp,#8]
    strb r0,[r6,#0x14]      /* publish only after all12 bytes are private */
    ldr r0,[sp,#12]
    ldr r12,=0x2bc1
    blx r12
    ldrb r2,[sp,#2]
    cmp r2,#9               /* corrupt length may not escape the shadow */
    bhi .Llegacy_return
    ldrb r0,[sp]
    ldrb r1,[sp,#1]
    add r3,sp,#3
    ldr r12,=0x4ef5
    blx r12                 /* native lookup, RPC, send AND last-report copy */
.Llegacy_return:
    ldr r0,[r7]
    ldr r1,=0x53465243
    cmp r0,r1
    add sp,#16
    beq .Llegacy_claimed
    /* R0/R1/flags are redefined at479E..47A2. No blocking call permits
     * lower-priority APP to claim before the native postlude reaches47AA. */
    RESUME 0x479e
.Llegacy_no_slot:
    ldr r0,[sp,#12]
    ldr r12,=0x2bc1
    blx r12
    add sp,#16
.Llegacy_claimed:
    /* Do not re-read native indexes or repost legacy work after a claim. */
    RESUME 0x47aa
END rc_native_legacy_snapshot
