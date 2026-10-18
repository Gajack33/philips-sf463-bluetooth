"""Execute the full Device Information callback with its real memcpy/strlen.

No GATT, ROM or peripheral stubs are provided; an unexpected external call fails.
The RAM state is a controlled fixture, not a hardware capture.
"""
from pathlib import Path
import binascii
import hashlib
import json
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'python-tools'))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS
from unicorn.arm_const import *
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS

BASELINE = (ROOT / 'candidates/usb/GVK1EH_B002FFv.06.06.bin').read_bytes()
IMAGE = (ROOT / 'candidates/diagnostic/GVK1EH_B002FFv.06.07.bin').read_bytes()
INITIAL_RAM = (ROOT / 'ram-init-emulated.bin').read_bytes()
STATE, UART, HW = 0x20000928, 0x20000dd0, 0x20000664
ATTR, UUID_PTR, OUT, LENGTH = 0x20003800, 0x20003840, 0x20003b00, 0x20003b80
RETURN, STACK = 0x30000000, 0x20004300
CALLEE_SAVED = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]


def word(emu, address, value):
    emu.mem_write(address, struct.pack('<I', value))


def read_callback(image=IMAGE, uuid=0x2a27, offset=0, maximum=64,
                  configuration='valid', seed=0):
    emu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    emu.mem_map(0, 0x20000)
    emu.mem_write(0, image)
    emu.mem_map(0x20000000, 0x8000)
    emu.mem_write(0x20000000, INITIAL_RAM)
    emu.mem_map(RETURN, 0x1000)
    # Real layouts recovered from the factory image; no hidden ROM API calls.
    emu.mem_write(STATE + 0xf, bytes([6]))
    emu.mem_write(STATE + 0x12, bytes([5]))
    emu.mem_write(STATE + 0x18, bytes([0xff]))
    emu.mem_write(STATE + 0x28, struct.pack('<H', 0x44 + seed))
    emu.mem_write(UART + 6, b'\x01')
    emu.mem_write(UART + 9, b'\x01')
    emu.mem_write(0x20003044, struct.pack('<H', 0x221 + seed))
    emu.mem_write(0x20000af0, b'\x45\x23')
    entry = 0x200027ec + 12
    word(emu, entry + 4, 0x20003860)
    emu.mem_write(entry + 8, b'\x02\x01\x01')
    word(emu, 0x20003860 + 12, 0x20003880)
    word(emu, 0x20003880, 0x200038a0)
    word(emu, 0x200038a0, 0x00012345)
    if configuration == 'missing_report':
        emu.mem_write(entry + 8, b'\0\0\0')
    elif configuration == 'invalid_attribute':
        word(emu, entry + 4, 0x40000000)
    elif configuration == 'unaligned_pointer':
        word(emu, 0x20003860 + 12, 0x20003881)
    elif configuration == 'invalid_table':
        word(emu, 0x20003880, 0x20005000)
    elif configuration == 'other_connection':
        word(emu, 0x200038a0, 0x00011234)
    elif configuration == 'disabled':
        word(emu, 0x200038a0, 0x00002345)
    elif configuration != 'valid':
        raise ValueError(configuration)
    values = {0x2a24: 0x2000061c, 0x2a25: 0x20000634, 0x2a26: 0x2000064c,
              0x2a27: HW, 0x2a28: 0x2000067c, 0x2a29: 0x20000694}
    word(emu, ATTR + 4, UUID_PTR)
    word(emu, ATTR + 12, values[uuid])
    emu.mem_write(UUID_PTR, struct.pack('<H', uuid))
    emu.mem_write(OUT, b'\xcc' * 128)
    emu.mem_write(LENGTH, b'\xcc\xcc')
    word(emu, STACK, offset)
    word(emu, STACK + 4, maximum)
    for reg, value in [(UC_ARM_REG_R0, 0x2345), (UC_ARM_REG_R1, ATTR),
                       (UC_ARM_REG_R2, OUT), (UC_ARM_REG_R3, LENGTH),
                       (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN | 1)]:
        emu.reg_write(reg, value)
    saved = {reg: 0xa5a50000 + i for i, reg in enumerate(CALLEE_SAVED)}
    for reg, value in saved.items():
        emu.reg_write(reg, value)
    before = bytes(emu.mem_read(0x20000000, 0x8000))
    emu.emu_start(0x5251, RETURN, timeout=1_000_000, count=30000)
    if emu.reg_read(UC_ARM_REG_PC) != RETURN:
        raise RuntimeError('Callback did not return')
    status = emu.reg_read(UC_ARM_REG_R0)
    length = struct.unpack('<H', bytes(emu.mem_read(LENGTH, 2)))[0]
    return {'emu': emu, 'status': status, 'length': length,
            'output': bytes(emu.mem_read(OUT, 128)), 'before': before, 'saved': saved}


class DiagnosticVerification(unittest.TestCase):
    def test_hardware_read_exposes_actual_state_and_fresh_key_values(self):
        for seed in (0, 1, 12):
            with self.subTest(seed=seed):
                r = read_callback(seed=seed)
                expected = bytes([6, 5, 1, 1]) + struct.pack('<H', 0x44 + seed) + struct.pack('<H', 0x221 + seed) + b'\x01\xff'
                self.assertEqual(r['status'], 0)
                self.assertEqual(r['length'], 20)
                self.assertEqual(r['output'][:20].decode(), expected.hex().upper())
                self.assertEqual(r['output'][20:], b'\xcc' * 108)

    def test_other_device_information_strings_are_unchanged(self):
        for uuid in (0x2a24, 0x2a25, 0x2a26, 0x2a28, 0x2a29):
            with self.subTest(uuid=hex(uuid)):
                baseline, actual = read_callback(BASELINE, uuid=uuid), read_callback(uuid=uuid)
                self.assertEqual((actual['status'], actual['length'], actual['output']),
                                 (baseline['status'], baseline['length'], baseline['output']))
                self.assertEqual(bytes(actual['emu'].mem_read(HW, 21)), INITIAL_RAM[HW - 0x20000000:HW - 0x20000000 + 21])

    def test_partial_reads_and_invalid_offset_obey_original_callback(self):
        full = read_callback()['output'][:20]
        for offset, maximum in ((0, 4), (4, 12), (19, 64), (20, 64), (0, 0)):
            with self.subTest(offset=offset, maximum=maximum):
                result = read_callback(offset=offset, maximum=maximum)
                expected = full[offset:offset + maximum]
                self.assertEqual(result['status'], 0)
                self.assertEqual(result['length'], len(expected))
                self.assertEqual(result['output'][:len(expected)], expected)
                self.assertEqual(result['output'][len(expected):], b'\xcc' * (128 - len(expected)))
        self.assertEqual(read_callback(offset=21)['status'], 7)

    def test_missing_invalid_or_other_connection_cccd_is_bounded(self):
        for case, expected in [('missing_report', 'FF'), ('invalid_attribute', 'FF'),
                               ('unaligned_pointer', 'FF'), ('invalid_table', 'FF'),
                               ('other_connection', 'FE'), ('disabled', '00')]:
            with self.subTest(case=case):
                result = read_callback(configuration=case)
                self.assertEqual(result['status'], 0)
                self.assertEqual(result['output'][16:18], expected.encode())

    def test_only_existing_hardware_buffer_output_and_stack_are_written(self):
        result = read_callback()
        emu = result['emu']
        after = bytes(emu.mem_read(0x20000000, 0x8000))
        allowed = [(HW, HW + 21), (OUT, OUT + 20), (LENGTH, LENGTH + 2), (STACK - 256, STACK)]
        unexpected = [hex(0x20000000 + i) for i, (a, b) in enumerate(zip(result['before'], after))
                      if a != b and not any(lo <= 0x20000000 + i < hi for lo, hi in allowed)]
        self.assertEqual(unexpected, [])
        for reg, value in result['saved'].items():
            self.assertEqual(emu.reg_read(reg), value)
        self.assertEqual(emu.reg_read(UC_ARM_REG_SP), STACK)

    def test_binary_integrity_hook_target_and_original_control_code(self):
        self.assertEqual(len(IMAGE), 118784)
        self.assertEqual(struct.unpack_from('<H', IMAGE)[0], binascii.crc_hqx(IMAGE[4:], 0))
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        hook = next(md.disasm(IMAGE[0x52b2:0x52b6], 0x52b2))
        self.assertEqual((hook.mnemonic, hook.op_str), ('bl', '#0x17000'))
        self.assertEqual(IMAGE[0x1af4:0x2b64], BASELINE[0x1af4:0x2b64])
        self.assertEqual(IMAGE[0x5348:0x575c], BASELINE[0x5348:0x575c])
        self.assertEqual(IMAGE[4:0x70], BASELINE[4:0x70])
        self.assertEqual(IMAGE[0x16e0:0x16f4], b'GVK1EH_B002FFv.06.07')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticVerification)
    names = [test.id() for test in suite]
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'passed': result.wasSuccessful(), 'methods': names, 'failures': len(result.failures),
              'errors': len(result.errors), 'candidate_sha256': hashlib.sha256(IMAGE).hexdigest(),
              'scope': __doc__, 'external_calls_stubbed': False,
              'hardware_validated': False, 'flashed': False}
    (ROOT / 'candidates/diagnostic/verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
