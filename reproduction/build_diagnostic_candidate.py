"""Expose a bounded, read-only state snapshot through Hardware Revision.

The front-HID prototype remains, but no UART command or permission guard is
changed. No new peripheral/ROM API is called by this diagnostic hook.
"""
from pathlib import Path
import binascii
import hashlib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'python-tools'))
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_LITTLE_ENDIAN

SOURCE = ROOT / 'candidates/usb/GVK1EH_B002FFv.06.06.bin'
DEST = ROOT / 'candidates/diagnostic/GVK1EH_B002FFv.06.07.bin'
HOOK = 0x52b2
STUB = 0x17000
ASSEMBLY = '''
cmp r3, #3
bne original_strlen
movw r1, #0x664
movt r1, #0x2000
cmp r0, r1
bne original_strlen
push {r4, r5, r6, lr}
mov r4, r0
movw r5, #0x928
movt r5, #0x2000
movw r6, #0xdd0
movt r6, #0x2000
ldrb r1, [r5, #0xf]
bl emit_hex
ldrb r1, [r5, #0x12]
bl emit_hex
ldrb r1, [r6, #6]
bl emit_hex
ldrb r1, [r6, #9]
bl emit_hex
ldrb r1, [r5, #0x28]
bl emit_hex
ldrb r1, [r5, #0x29]
bl emit_hex
movw r2, #0x3044
movt r2, #0x2000
ldrb r1, [r2]
bl emit_hex
movw r2, #0x3044
movt r2, #0x2000
ldrb r1, [r2, #1]
bl emit_hex
movw r2, #0x27ec
movt r2, #0x2000
movs r3, #4
find_consumer:
ldrb r1, [r2, #8]
cmp r1, #2
bne next_report
ldrb r1, [r2, #9]
cmp r1, #1
bne next_report
ldrb r1, [r2, #10]
cmp r1, #1
bne next_report
ldr r2, [r2, #4]
adds r2, #12
bl checked_deref
cmp.w r12, #0
beq unknown_cfg
bl checked_deref
cmp.w r12, #0
beq unknown_cfg
bl checked_deref
cmp.w r12, #0
beq unknown_cfg
movw r1, #0xaf0
movt r1, #0x2000
ldrh r1, [r1]
uxth r3, r2
cmp r1, r3
bne other_connection
lsrs r1, r2, #16
uxtb r1, r1
b cfg_done
next_report:
adds r2, #12
subs r3, #1
bne find_consumer
unknown_cfg:
movs r1, #0xff
b cfg_done
other_connection:
movs r1, #0xfe
cfg_done:
bl emit_hex
ldrb r1, [r5, #0x18]
bl emit_hex
movs r1, #0
strb r1, [r0]
mov r0, r4
pop.w {r4, r5, r6, lr}
original_strlen:
b.w 0x74a4

emit_hex:
lsrs r2, r1, #4
ands r2, r2, #15
adds r2, #48
cmp r2, #57
it hi
addhi r2, #7
strb r2, [r0], #1
ands r1, r1, #15
adds r1, #48
cmp r1, #57
it hi
addhi r1, #7
strb r1, [r0], #1
bx lr

checked_deref:
tst.w r2, #3
bne invalid_pointer
lsrs r1, r2, #16
movw r12, #0x2000
cmp r1, r12
bne invalid_pointer
uxth r1, r2
movw r12, #0x4ffc
cmp r1, r12
bhi invalid_pointer
ldr r2, [r2]
movw r12, #1
bx lr
invalid_pointer:
movs r2, #0
movw r12, #0
bx lr
'''


def build():
    original = SOURCE.read_bytes()
    if hashlib.sha256(original).hexdigest() != '2ae337f863fd83cf951cd4e53c22cfefb94a93fd725db8531ecbb974f0f752d8':
        raise ValueError('Source candidate differs from installed v.06.06')
    if original[HOOK:HOOK + 4] != bytes.fromhex('02f0f7f8'):
        raise ValueError('Original strlen call differs')
    assembler = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_LITTLE_ENDIAN)
    stub = bytes(assembler.asm(ASSEMBLY, addr=STUB)[0])
    call = bytes(assembler.asm(f'bl {STUB:#x}', addr=HOOK)[0])
    if len(call) != 4 or original[STUB:STUB + len(stub)] != b'\xff' * len(stub):
        raise ValueError('Unexpected branch size or flash space is occupied')
    image = bytearray(original)
    image[HOOK:HOOK + 4] = call
    image[STUB:STUB + len(stub)] = stub
    image[0x16e0:0x16f4] = b'GVK1EH_B002FFv.06.07'
    struct.pack_into('<H', image, 0, binascii.crc_hqx(image[4:], 0))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.read_bytes() != image:
        raise FileExistsError('Different diagnostic candidate already exists')
    DEST.write_bytes(image)
    (DEST.parent / 'hardware-revision-hook.asm').write_text(ASSEMBLY, encoding='utf-8')
    report = {'status': 'OFFLINE - NOT FLASHED', 'candidate_sha256': hashlib.sha256(image).hexdigest(),
              'version': 'GVK1EH_B002FFv.06.07 - local diagnostic build',
              'hook_offset': hex(HOOK), 'hook_before': original[HOOK:HOOK + 4].hex(),
              'hook_after': call.hex(), 'stub_address': hex(STUB), 'stub_length': len(stub),
              'target': 'Device Information Hardware Revision (2a27), RAM buffer 0x20000664',
              'fields_hex_pairs': ['role', 'hid_ready', 'uart_active', 'uart_face',
                                   'last_front_usage_low', 'last_front_usage_high',
                                   'last_consumer_usage_low', 'last_consumer_usage_high',
                                   'consumer_cccd_first_slot', 'last_front_index'],
              'cccd_special_values': {'FF': 'Unknown/missing pointer or report', 'FE': 'First slot belongs to another connection'},
              'scope': 'Snapshot of existing state only; no commands to UART, no ROM/GAP/GATT API added',
              'mutable_buffer_bytes': 21,
              'unproven': 'No hardware validation; neither root cause nor front Bluetooth operation established'}
    DEST.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    build()
