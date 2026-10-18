"""Real Thumb native-ABI bridge checks; ROM/BLE/electrical behavior is not emulated.

Compilation and patched images stay in temporary memory/build artifacts. No
firmware .bin, USB archive or device mutation is performed by these tests.
NativeMachine/compile_integration are reusable for explicit runtime API stubs.
"""
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_APSR, UC_ARM_REG_XPSR)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sf463_native_builder", ROOT / "firmware/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
STOCK = (ROOT / "firmware/original/GVK1EH_B002FFv.06.05.bin").read_bytes()
BASELINE = (ROOT / "firmware/RCFW/GVK1EH_B002FFv.06.07.bin").read_bytes()
APP, HID, UART = 0x20000928, 0x20000AD8, 0x20000DD0
STACK, INPUT, RETURN = 0x20007F00, 0x20006000, 0x30000000
REGISTERS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_APSR]
ARGUMENTS = REGISTERS[:4]
VOLATILE = ARGUMENTS + [UC_ARM_REG_R12]


def compile_integration(directory, variant="diagnostic"):
    manifest = json.loads((ROOT / "firmware/hooks.json").read_text(encoding="utf-8"))
    payload, symbols, invocation = build.compile_patch(manifest, variant,
        os.environ.get("SF463_COMPILER"), Path(directory))
    image, patches = build.apply_image(STOCK, BASELINE, manifest, variant, payload,
        symbols, require_qualified=False)
    return {"payload": payload, "symbols": symbols, "image": image,
            "manifest": manifest, "patches": patches, "compiler": invocation}


class NativeMachine:
    """No implicit native API stubs. Each test must explicitly supply its seams."""
    def __init__(self, compiled, patched=False):
        self.compiled, self.symbols = compiled, compiled["symbols"]
        self.image = compiled["image"]
        self.emu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.emu.mem_map(0, 0x20000)
        self.emu.mem_write(0, compiled["image"] if patched else STOCK)
        if not patched:
            self.emu.mem_write(build.PATCH_START, compiled["payload"])
        self.emu.mem_map(0x20000000, 0x10000)
        self.emu.mem_map(RETURN, 0x1000)
        self.stubs, self.trace = {}, []
        self.stop = RETURN
        self.emu.hook_add(UC_HOOK_CODE, self._instruction)
        self.seed()

    def seed(self):
        for i, register in enumerate(REGISTERS[:13]):
            self.emu.reg_write(register, 0x11110000 + i * 0x10101)
        self.emu.reg_write(UC_ARM_REG_SP, STACK)
        self.emu.reg_write(UC_ARM_REG_LR, RETURN | 1)
        self.emu.reg_write(UC_ARM_REG_XPSR, 0x01000000 | 0xB8000000)

    def _instruction(self, emu, address, size, data):
        if address == self.stop:
            emu.emu_stop()
        elif address in self.stubs:
            self.trace.append(address)
            self.stubs[address](self)

    def stub(self, address, callback):
        if isinstance(address, str):
            address = self.symbols[address]
        self.stubs[address & ~1] = callback

    def ret(self, low=None, high=None, clobber=False):
        if clobber:
            for register in VOLATILE:
                self.emu.reg_write(register, 0xEFEFEFEF)
            self.emu.reg_write(UC_ARM_REG_APSR, 0x20000000)
        if low is not None:
            self.emu.reg_write(UC_ARM_REG_R0, low & 0xFFFFFFFF)
        if high is not None:
            self.emu.reg_write(UC_ARM_REG_R1, high & 0xFFFFFFFF)
        self.emu.reg_write(UC_ARM_REG_PC, self.emu.reg_read(UC_ARM_REG_LR))

    def argument(self, index):
        if index < 4:
            return self.emu.reg_read(ARGUMENTS[index])
        return self.read32(self.emu.reg_read(UC_ARM_REG_SP) + (index - 4) * 4)

    def write32(self, address, value):
        self.emu.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def read32(self, address):
        return struct.unpack("<I", self.emu.mem_read(address, 4))[0]

    def address(self, name):
        return self.symbols[name] & ~1

    def read(self, address, size):
        return bytes(self.emu.mem_read(address, size))

    def write(self, address, data):
        self.emu.mem_write(address, bytes(data))

    def run(self, entry, stop=RETURN, budget=250000):
        self.stop = stop
        start = self.symbols[entry] if isinstance(entry, str) else entry
        self.emu.emu_start(start | 1, 0, timeout=1_000_000, count=budget)
        if self.emu.reg_read(UC_ARM_REG_PC) != stop:
            raise AssertionError(f"{entry}: did not reach {stop:#x} within budget")
        return self.emu.reg_read(UC_ARM_REG_R0)

    def call(self, entry, *arguments):
        self.seed()
        saved = [self.emu.reg_read(r) for r in REGISTERS[4:12]]
        for index, value in enumerate(arguments):
            if index < 4:
                self.emu.reg_write(ARGUMENTS[index], value & 0xFFFFFFFF)
            else:
                self.write32(STACK + (index - 4) * 4, value)
        result = self.run(entry)
        if self.emu.reg_read(UC_ARM_REG_SP) != STACK:
            raise AssertionError(f"{entry}: native call did not restore SP")
        if [self.emu.reg_read(r) for r in REGISTERS[4:12]] != saved:
            raise AssertionError(f"{entry}: native call clobbered callee-saved registers")
        return result

    def snapshot(self):
        return ([self.emu.reg_read(r) for r in REGISTERS],
                bytes(self.emu.mem_read(STACK - 128, 128)))


NativeFixture = NativeMachine


class NativeAdapterAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-native-abi-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled = compile_integration(cls.temporary.name)

    def machine(self):
        return NativeMachine(self.compiled)

    def test_exact_manifest_windows_cover_complete_factory_instructions(self):
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        for hook in self.compiled["manifest"]["hooks"]:
            with self.subTest(hook=hook["name"]):
                at = int(hook["offset"], 0)
                expected = bytes.fromhex(hook["expected_hex"])
                self.assertEqual(STOCK[at:at + len(expected)], expected)
                if hook["name"] == "app-lifecycle-event-mask":
                    # This one reviewed window is a32-bit literal, not code.
                    # Check both masks and its unchanged PC-relative reader;
                    # all instruction hooks still require complete decoding.
                    self.assertEqual(at, 0x22B4)
                    self.assertEqual(struct.unpack("<I", expected)[0], 0xC00003C0)
                    self.assertEqual(struct.unpack_from("<I", self.compiled["image"], at)[0], 0xC00007C0)
                    self.assertEqual(self.compiled["image"][0x179C:0x17A0], STOCK[0x179C:0x17A0])
                    continue
                instructions = list(decoder.disasm(expected, at))
                self.assertEqual(sum(i.size for i in instructions), len(expected))
                self.assertTrue(instructions)
        manifest = self.compiled["manifest"]
        self.assertIs(type(manifest["integration_qualified"]), bool)
        self.assertIsInstance(manifest["integration_evidence"], list)
        if manifest["integration_qualified"]:
            # CI also emulates Clang builds independently of the qualified
            # release compiler. Check the qualified source/hook/proof binding
            # here; image export still requires its exact per-variant image
            # hash in build.apply_image(require_qualified=True).
            build.validate_evidence(manifest)

    def test_all_original_prologues_preserve_register_flags_stack_and_native_resume(self):
        cases = [("rear", 0x1A90, 0x1A94), ("front", 0x1ABC, 0x1AC2),
            ("event_drain", 0x1878, 0x187E), ("consumer", 0x21DC, 0x21E0),
            ("keyboard", 0x2170, 0x2174), ("hid_submit", 0x488E, 0x4892),
            ("control", 0x48F4, 0x48F8),
            ("link_event", 0x4D22, 0x4D26), ("hid_message", 0x4C2A, 0x4C2E),
            ("attr_write", 0x4AB0, 0x4AB4),
            ("uart_receive", 0x551A, 0x551E), ("timer", 0x50B8, 0x50BC),
            ("uart_close", 0x53A2, 0x53A8), ("uart_worker", 0x5648, 0x564C),
            ("device_info", 0x5250, 0x5254)]
        for name, original, resume in cases:
            with self.subTest(bridge=name):
                native, bridge = self.machine(), self.machine()
                native.run(original, resume)
                bridge.run("rc_original_" + name, resume)
                self.assertEqual(bridge.snapshot(), native.snapshot())

    def test_five_and_six_argument_trampolines_keep_stack_arguments_at_native_offsets(self):
        for symbol, resume, pushed, arguments in [
            ("rc_original_attr_write", 0x4AB4, 40, [0x11223344]),
            ("rc_original_device_info", 0x5254, 48, [0x1234, 0x78])]:
            with self.subTest(symbol=symbol):
                m = self.machine()
                for i, value in enumerate(arguments): m.write32(STACK + i * 4, value)
                m.run(symbol, resume)
                self.assertEqual(m.emu.reg_read(UC_ARM_REG_SP), STACK - pushed)
                for i, value in enumerate(arguments):
                    self.assertEqual(m.read32(m.emu.reg_read(UC_ARM_REG_SP) + pushed + i * 4), value)

    def test_hid_drain_keeps_live_registers_and_native_fallback_for_both_event_masks(self):
        for active, mask, target, expected_calls in [(0, 0, 0x47AA, 0),
                (0, 4, 0x4770, 0), (1, 0, 0x47AA, 0), (1, 4, 0x47AA, 1)]:
            with self.subTest(active=active, mask=mask):
                m = self.machine(); m.emu.reg_write(UC_ARM_REG_R5, mask); calls=[]
                m.stub("rc_enabled", lambda x: x.ret(active, clobber=True))
                def worker(x): calls.append(1); x.ret(clobber=True)
                m.stub("rc_hid_worker", worker)
                before = [m.emu.reg_read(r) for r in REGISTERS]
                m.run("rc_hid_drain", target)
                after = [m.emu.reg_read(r) for r in REGISTERS]
                if active:
                    self.assertEqual(after, before)
                else:
                    for i in range(len(REGISTERS) - 1):
                        if i != 1: self.assertEqual(after[i], before[i])
                    self.assertEqual(after[1], (mask << 29) & 0xFFFFFFFF)
                self.assertEqual(len(calls), expected_calls)

    def test_front_gate_preserves_voice_press_release_and_inactive_readiness(self):
        cases = [(1, 0x45, 0x45, 0, 0x1D30), (1, 0, 0x45, 0, 0x1D30),
            (1, 0x221, 0x221, 0, 0x1D58), (1, 0, 0x221, 0, 0x1D58),
            (1, 0x221, 0x221, 5, 0x1D30), (0, 0x45, 0x45, 0, 0x1D58),
            (0, 0x45, 0x45, 5, 0x1D30)]
        for active, usage, last, ready, target in cases:
            with self.subTest(active=active, usage=usage, last=last, ready=ready):
                m=self.machine();m.emu.reg_write(UC_ARM_REG_R4,usage);m.emu.reg_write(UC_ARM_REG_R1,last)
                m.emu.reg_write(UC_ARM_REG_R5,APP);m.emu.reg_write(UC_ARM_REG_R8,0x221)
                m.emu.mem_write(APP+0x12,bytes([ready]));m.stub("rc_enabled",lambda x:x.ret(active,clobber=True))
                before=[m.emu.reg_read(r) for r in REGISTERS]
                m.run("rc_front_gate",target)
                for i in range(1,len(REGISTERS)-1):self.assertEqual(m.emu.reg_read(REGISTERS[i]),before[i])

    def test_event_rest_matches_native_epilogue_and_remaining_event_handlers(self):
        for mask in [0, 8, 0x20, 0x800]:
            with self.subTest(mask=mask):
                native,bridge=self.machine(),self.machine()
                for m in [native,bridge]:
                    m.emu.reg_write(UC_ARM_REG_R0,mask)
                    for address in [0x25BC,0xF2,0x270C]:m.stub(address,lambda x:x.ret())
                native.emu.mem_write(APP+0x20,struct.pack("<H",mask))
                native.run(0x1878);bridge.run("rc_native_event_rest")
                self.assertEqual(bridge.snapshot(),native.snapshot())
                self.assertEqual(bytes(bridge.emu.mem_read(APP,0x1A0)),bytes(native.emu.mem_read(APP,0x1A0)))

    def test_uart_frame_helper_runs_same_parser_callbacks_and_ack_close_logic(self):
        frames=[b"\xfe\x01\x01\x24\xff\xff",b"\xfe\x01\x00\xff\xff\xff",
            b"\xfe\x01\x02\x26\x29\xff",b"\xfe\x00\xfa\x20\xff\xff",
            b"\xfe\x01\xfb\xff\xff\xff",b"\xfe\x00\xff\xff\xff\xff"]
        for frame in frames:
            with self.subTest(frame=frame.hex()):
                native,bridge=self.machine(),self.machine();records=[]
                frame_pointer=INPUT+1  # uint8_t* deliberately need not be word-aligned.
                for index,m in enumerate([native,bridge]):
                    captured=[];records.append(captured)
                    m.emu.mem_write(frame_pointer,frame);m.emu.reg_write(UC_ARM_REG_R0,frame_pointer)
                    m.emu.mem_write(UART+2,b"\xff");m.write32(UART+0x18,0x1ABC|1)
                    def read(x,f=frame):
                        x.emu.mem_write(x.argument(1),f);x.ret(len(f))
                    def callback(x,result=captured):
                        count,ptr,special=x.argument(0),x.argument(1),x.argument(2)
                        result.append((count,special,bytes(x.emu.mem_read(ptr,1 if special else count))))
                        x.ret()
                    m.stub(0x756A,read);m.stub(0x1ABC,callback)
                    for address in [0xF2,0xF6]:m.stub(address,lambda x:x.ret())
                native.run(0x551A);bridge.run("rc_native_uart_frame")
                self.assertEqual(records[1],records[0])
                # The original read BL leaves its internal return address in
                # caller-clobbered LR when no later call occurs (ACK/close).
                # The helper skips that read; compare every other register,
                # APSR and the complete local stack, not this internal LR.
                bridge_registers,bridge_stack=bridge.snapshot()
                native_registers,native_stack=native.snapshot()
                for i in range(len(REGISTERS)):
                    if REGISTERS[i] != UC_ARM_REG_LR:
                        self.assertEqual(bridge_registers[i],native_registers[i])
                self.assertEqual(bridge_stack,native_stack)
                self.assertEqual(bytes(bridge.emu.mem_read(UART,0xB0)),bytes(native.emu.mem_read(UART,0xB0)))
                if frame[1:4]==b"\x01\x01\x24":
                    self.assertEqual(records[1],[(0,0xF1,b"\x01"),(1,0,b"\x24")])


if __name__ == "__main__":
    unittest.main()
