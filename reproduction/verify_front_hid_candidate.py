"""Execute factory/candidate Thumb dispatch and HID serialization in Unicorn.

All other calls are explicitly stubbed. This is a narrow software comparison,
not a simulation of the remote MCU, BLE stack, UART events, boot or TV standby.
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
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

FACTORY = (ROOT / 'originals/ro/BTRC_FW/GVK1EH_B002FFv.06.05.bin').read_bytes()
CANDIDATE = (ROOT / 'candidates/usb/GVK1EH_B002FFv.06.06.bin').read_bytes()
RAM = (ROOT / 'ram-init-emulated.bin').read_bytes()
STATE = 0x20000928
RETURN = 0x30000000
KEYS = {'power': (0, 0x30), 'home': (40, 0x223), 'up': (12, 0x42),
        'down': (32, 0x43), 'left': (24, 0x44), 'right': (36, 0x45),
        'ok': (20, 0x41), 'volume_up': (33, 0xe9),
        'volume_down': (5, 0xea), 'mute': (41, 0xe2)}
OBSERVATIONS = []


class Dispatch:
    def __init__(self, image, ready=5, bonded=True, role=6):
        self.emu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.emu.mem_map(0, 0x20000)
        self.emu.mem_write(0, image)
        self.emu.mem_map(0x20000000, 0x8000)
        self.emu.mem_write(0x20000000, RAM)
        self.emu.mem_map(RETURN, 0x1000)
        self.emu.mem_write(STATE + 0x12, bytes([ready]))
        self.emu.mem_write(STATE + 0xf, bytes([role]))
        self.emu.mem_write(STATE + 0x18, b'\xff')
        self.emu.mem_write(STATE + 0x28, b'\0\0')
        self.bonded = bonded
        self.reports = []
        self.calls = []
        disassembler = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        self.stubs = set()
        for start, end in [(0x1af4, 0x1dac), (0x21dc, 0x220a)]:
            for insn in disassembler.disasm(image[start:end], start):
                if insn.mnemonic == 'bl' and insn.op_str.startswith('#'):
                    address = int(insn.op_str[1:], 0)
                    if address != 0x21dc:
                        self.stubs.add(address)
        self.emu.hook_add(UC_HOOK_CODE, self.hook)

    def hook(self, emu, address, size, _):
        if address not in self.stubs:
            return
        args = [emu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        self.calls.append({'address': hex(address), 'args': args})
        if address == 0x488e:
            self.reports.append({'id': args[0], 'type': args[1],
                                 'data': bytes(emu.mem_read(args[3], args[2])).hex()})
        emu.reg_write(UC_ARM_REG_R0, int(self.bonded) if address == 0x26ee else 0)
        emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))

    def press_release(self, index):
        for value in (index, 0xff):
            self.emu.reg_write(UC_ARM_REG_R0, value)
            self.emu.reg_write(UC_ARM_REG_SP, 0x20004300)
            self.emu.reg_write(UC_ARM_REG_LR, RETURN | 1)
            self.emu.emu_start(0x1af5, RETURN, timeout=1_000_000, count=20000)
            if self.emu.reg_read(UC_ARM_REG_PC) != RETURN:
                raise RuntimeError('Dispatcher failed to return within bound')
        return self.reports


class CandidateVerification(unittest.TestCase):
    def test_only_instruction_revision_and_crc_change(self):
        changes = {i for i, (a, b) in enumerate(zip(FACTORY, CANDIDATE)) if a != b}
        self.assertEqual(changes, {0, 1, 0x16f3, 0x1d28, 0x1d29})
        self.assertEqual(len(FACTORY), len(CANDIDATE))
        self.assertEqual(binascii.crc_hqx(CANDIDATE[4:], 0), struct.unpack_from('<H', CANDIDATE)[0])
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        self.assertEqual(next(md.disasm(CANDIDATE[0x1d28:0x1d2a], 0x1d28)).mnemonic, 'nop')
        self.assertEqual(CANDIDATE[0x16e0:0x16f4], b'GVK1EH_B002FFv.06.06')

    def test_consumer_descriptor_accepts_front_key_usages(self):
        # Consumer Control, report ID 2, two 12-bit array fields, usages 0..0x7ff.
        descriptor = bytes.fromhex('050c0901a1018502750c9502150026ff0719002aff078100c0')
        self.assertEqual(FACTORY[0x14d20:0x14d39], descriptor)
        self.assertEqual(CANDIDATE[0x14d20:0x14d39], descriptor)
        for _, usage in KEYS.values():
            encoded = int.from_bytes(struct.pack('<HB', usage, 0), 'little')
            self.assertEqual(encoded & 0xfff, usage)
            self.assertEqual(encoded >> 12, 0)
            self.assertLessEqual(usage, 0x7ff)

    def test_front_keys_have_press_release_reports_when_ready(self):
        for name, (index, usage) in KEYS.items():
            with self.subTest(key=name):
                actual_usage = struct.unpack_from('<H', FACTORY, 0x13b84 + index * 4)[0]
                self.assertEqual(actual_usage, usage, 'Independent key-label and firmware-map agreement')
                original = Dispatch(FACTORY)
                patched = Dispatch(CANDIDATE)
                before = original.press_release(index)
                after = patched.press_release(index)
                expected = [{'id': 2, 'type': 1, 'data': struct.pack('<HB', usage, 0).hex()},
                            {'id': 2, 'type': 1, 'data': '000000'}]
                self.assertEqual(after, expected)
                if name != 'ok':
                    self.assertEqual(before, [])
                self.assertEqual(bytes(patched.emu.mem_read(STATE + 0x18, 1)), b'\xff')
                OBSERVATIONS.append({'key': name, 'factory': before, 'candidate': after})

    def test_not_ready_and_unbonded_guards_remain(self):
        for ready, bonded in [(0, True), (3, True), (6, True), (5, False)]:
            for name in ('right', 'power', 'volume_up'):
                with self.subTest(ready=ready, bonded=bonded, key=name):
                    emu = Dispatch(CANDIDATE, ready=ready, bonded=bonded)
                    self.assertEqual(emu.press_release(KEYS[name][0]), [])

    def test_voice_application_control_path_unchanged(self):
        original, patched = Dispatch(FACTORY), Dispatch(CANDIDATE)
        self.assertEqual(original.press_release(4), patched.press_release(4))
        self.assertEqual(original.calls, patched.calls)
        self.assertEqual(bytes(original.emu.mem_read(STATE, 0x190)),
                         bytes(patched.emu.mem_read(STATE, 0x190)))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CandidateVerification))
    report = {'scope': __doc__, 'passed': result.wasSuccessful(), 'test_methods': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'factory_sha256': hashlib.sha256(FACTORY).hexdigest(),
              'candidate_sha256': hashlib.sha256(CANDIDATE).hexdigest(),
              'observations': OBSERVATIONS}
    (ROOT / 'candidates/emulation-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
