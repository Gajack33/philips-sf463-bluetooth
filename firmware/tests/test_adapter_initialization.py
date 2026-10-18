"""Actual Thumb adapter initialization and diagnostic callback contracts.

Native allocator/identity/clock calls below are explicit API fixtures; this is
not hardware, allocator internals, scheduler concurrency, or recovery proof.
The actual linked adapter/core and native Device Information code are executed.
"""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
    UC_ARM_REG_R11, UC_ARM_REG_SP)

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sf463_init_native_fixture", HERE / "test_native_adapter.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
APP, HID, UART, STACK = native.APP, native.HID, native.UART, native.STACK
ALLOC, QUEUE, HW = 0x20003200, 0x200027C8, 0x20000664
ATTR, UUID, OUT, LENGTH = 0x20003E00, 0x20003E40, 0x20006000, 0x20006100
SAVED = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
         UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]


class InitMachine(native.NativeMachine):
    def __init__(self, compiled, case):
        super().__init__(compiled, patched=True)
        self.case, self.depth, self.maximum_depth = case, 0, 0
        self.native_init_count, self.heap_queries = 0, []
        self.allocations, self.frees, self.writes = [], [], []
        self.free_before, self.free_after, self.largest = 3000, 2400, 2500
        self.allocate_result, self.tick = ALLOC, 1000
        self.bond_count, self.bond_status = 1, 0
        self.saved_peer = bytes([1, 2, 3, 4, 5, 6])
        self.connected_peer = self.saved_peer
        self.emu.mem_write(QUEUE, bytes(range(36)))
        self.write32(HID + 0x1C, 0x20006200)
        self.write32(APP + 0x2C, 0x20006300)
        self.emu.mem_write(HID + 0x0D, b"\x06")
        self.emu.mem_write(HID + 0x14, b"\0\0")
        self.emu.mem_write(0x20001790, b"\x01")
        self.write_guard = self.emu.hook_add(UC_HOOK_MEM_WRITE, self.check_write)
        self.stub(0x13E4, self.native_init)
        self.stub(0x2BAA, self.enter)
        self.stub(0x2BC0, self.leave)
        self.stub(0x2D54, self.stats)
        self.stub(0x2C3E, self.allocate)
        self.stub(0x2CD0, self.free)
        self.stub(0x2B8C, lambda m: m.ret(self.tick, clobber=True))
        self.stub(0x26EE, lambda m: self.outside(m, self.bond_count))
        self.stub(0x34B8, self.bond_get)
        self.stub(0x3874, self.peer_get)
        self.stub(0x4EC4, lambda m: self.outside(m, 0))

    def check_write(self, emu, access, address, size, value, data):
        allowed = [(ALLOC, ALLOC + 640), (QUEUE, QUEUE + 36), (HID + 0x14, HID + 0x16),
                   (STACK - 0x1000, STACK + 32), (HW, HW + 21),
                   (OUT, OUT + 128), (LENGTH, LENGTH + 2)]
        self.case.assertTrue(any(start <= address and address + size <= end for start, end in allowed),
                             f"Unexpected adapter write {address:#x}+{size}")
        self.writes.append((address, size))

    def native_init(self, m):
        self.case.assertEqual(self.depth, 0)
        self.native_init_count += 1
        m.ret(clobber=True)

    def outside(self, m, result=0):
        self.case.assertEqual(self.depth, 0, "blocking/native query must stay outside the critical gate")
        m.ret(result, clobber=True)

    def enter(self, m):
        self.case.assertEqual(self.depth, 0, "core gate must not be recursively acquired")
        self.depth += 1
        self.maximum_depth = max(self.maximum_depth, self.depth)
        m.ret(0x12345678, clobber=True)

    def leave(self, m):
        self.case.assertEqual((self.depth, m.argument(0)), (1, 0x12345678))
        self.depth -= 1
        m.ret(clobber=True)

    def stats(self, m):
        self.case.assertEqual(self.depth, 0, "heap statistics may lock internally")
        free = self.free_after if self.allocations else self.free_before
        self.heap_queries.append((free, self.depth))
        m.emu.mem_write(m.argument(0), struct.pack("<III", 4096, free, self.largest))
        m.ret(clobber=True)

    def allocate(self, m):
        self.case.assertEqual(self.depth, 0)
        self.allocations.append(m.argument(0))
        m.ret(self.allocate_result, clobber=True)

    def free(self, m):
        self.case.assertEqual(self.depth, 0)
        self.frees.append(m.argument(0))
        m.ret(clobber=True)

    def bond_get(self, m):
        self.case.assertEqual(self.depth, 0)
        self.case.assertEqual((m.argument(0), m.argument(2)), (0x10, 0x419))
        m.emu.mem_write(m.argument(3), self.saved_peer)
        m.ret(self.bond_status, clobber=True)

    def peer_get(self, m):
        self.case.assertEqual(self.depth, 0)
        self.case.assertEqual(m.argument(0), 0x315)
        m.emu.mem_write(m.argument(1), self.connected_peer)
        m.ret(0, clobber=True)

    def checked_call(self, symbol, *arguments):
        result = self.call(symbol, *arguments)
        self.case.assertEqual(self.depth, 0)
        self.case.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), STACK)
        expected = [0x11110000 + index * 0x10101 for index in range(4, 12)]
        self.case.assertEqual([self.emu.reg_read(register) for register in SAVED], expected)
        return result

    def configure_attribute(self, uuid=0x2A27, value=HW):
        self.write32(ATTR + 4, UUID)
        self.write32(ATTR + 12, value)
        self.emu.mem_write(UUID, struct.pack("<H", uuid))

    def read_info(self, offset=0, maximum=20):
        self.emu.mem_write(OUT, b"\xcc" * 128)
        self.emu.mem_write(LENGTH, b"\xee\xee\xaa\xbb")
        status = self.checked_call(0x5250, 0x2345, ATTR, OUT, LENGTH, offset, maximum)
        self.case.assertEqual(bytes(self.emu.mem_read(LENGTH + 2, 2)), b"\xaa\xbb",
                              "callback length is uint16_t, not uint32_t")
        size = struct.unpack("<H", self.emu.mem_read(LENGTH, 2))[0]
        output = bytes(self.emu.mem_read(OUT, 128))
        self.case.assertEqual(output[size:], b"\xcc" * (128 - size))
        return status, size, output[:size]


class AdapterInitializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-initialization-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled = {}
        for variant in ("diagnostic", "usage"):
            path = Path(cls.temporary.name) / variant
            path.mkdir()
            cls.compiled[variant] = native.compile_integration(path, variant)

    def machine(self, variant="diagnostic"):
        return InitMachine(self.compiled[variant], self)

    def successful_size(self):
        m = self.machine()
        m.checked_call("rc_app_init")
        self.assertEqual(len(m.allocations), 1)
        return m.allocations[0]

    def test_initialization_claims_only_after_one_bounded_allocation_and_preserves_registers(self):
        m = self.machine()
        before = bytes(m.emu.mem_read(0x20000000, 0x5000))
        m.checked_call("rc_app_init")
        self.assertEqual(len(m.allocations), 1)
        size = m.allocations[0]
        self.assertGreater(size, 488)
        self.assertLessEqual(size, 640)
        self.assertEqual(m.read32(QUEUE), 0x53465243)
        self.assertEqual(m.read32(QUEUE + 4), ALLOC)
        self.assertEqual(m.read32(QUEUE + 8), 0)
        self.assertEqual(m.frees, [])
        self.assertEqual(m.checked_call("rc_enabled"), 1)
        self.assertEqual([depth for _, depth in m.heap_queries], [0, 0])
        after = bytes(m.emu.mem_read(0x20000000, 0x5000))
        allowed = [(ALLOC, ALLOC + size), (QUEUE, QUEUE + 36), (HID + 0x14, HID + 0x16)]
        for index, (a, b) in enumerate(zip(before, after)):
            if a != b:
                at = 0x20000000 + index
                self.assertTrue(any(start <= at < end for start, end in allowed), hex(at))
        m.checked_call("rc_app_init")
        self.assertEqual(len(m.allocations), 1, "no allocation on a repeated adapter initialization")

    def test_heap_prechecks_postfree_reserve_and_allocation_failure_leave_native_queue_intact(self):
        size = self.successful_size()
        for condition in ("insufficient-total", "fragmented", "postfree-767", "allocation-failure"):
            with self.subTest(condition=condition):
                m = self.machine()
                if condition == "insufficient-total": m.free_before = size + 8 + 768 - 1
                if condition == "fragmented": m.largest = size - 1
                if condition == "postfree-767": m.free_after = 767
                if condition == "allocation-failure": m.allocate_result = 0
                before = bytes(m.emu.mem_read(QUEUE, 36))
                m.checked_call("rc_app_init")
                self.assertEqual(bytes(m.emu.mem_read(QUEUE, 36)), before)
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                self.assertEqual(m.frees, [ALLOC] if condition == "postfree-767" else [])
                self.assertEqual(len(m.allocations), int(condition in ("postfree-767", "allocation-failure")))
        m = self.machine(); m.free_after = 768
        m.checked_call("rc_app_init")
        self.assertEqual(m.checked_call("rc_enabled"), 1, "exactly 768 free bytes satisfies the reserve")

    def test_missing_identity_handles_or_active_native_queue_never_claim_storage(self):
        for condition in ("no-hid-semaphore", "no-bond", "two-bonds", "zero-peer", "bond-read-failed",
                          "pending-native-report", "active-keyboard", "active-consumer"):
            with self.subTest(condition=condition):
                m = self.machine()
                if condition == "no-hid-semaphore": m.write32(HID + 0x1C, 0)
                if condition == "no-bond": m.bond_count = 0
                if condition == "two-bonds": m.bond_count = 2
                if condition == "zero-peer": m.saved_peer = bytes(6)
                if condition == "bond-read-failed": m.bond_status = 1
                if condition == "pending-native-report": m.emu.mem_write(HID + 0x14, b"\0\x01")
                if condition == "active-keyboard": m.emu.mem_write(APP + 0x20, b"\x01\0")
                if condition == "active-consumer": m.emu.mem_write(APP + 0x20, b"\x10\0")
                before = bytes(m.emu.mem_read(QUEUE, 36))
                m.checked_call("rc_app_init")
                self.assertEqual(bytes(m.emu.mem_read(QUEUE, 36)), before)
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                if condition in ("pending-native-report", "active-keyboard", "active-consumer"):
                    self.assertEqual((len(m.allocations), m.frees), (1, [ALLOC]))
                else:
                    self.assertEqual(m.allocations, [])

    def test_diagnostic_partial_reads_reuse_one_snapshot_and_write_only_uint16_length(self):
        m = self.machine(); m.checked_call("rc_app_init"); m.configure_attribute()
        first = m.read_info(0, 7)
        snapshot = bytes(m.emu.mem_read(HW, 20))
        self.assertEqual(first, (0, 7, snapshot[:7]))
        self.assertEqual(snapshot[:4], b"0001")  # page zero, active adapter
        queries = len(m.heap_queries)
        m.tick += 500000
        second, third = m.read_info(7, 7), m.read_info(14, 20)
        self.assertEqual(first[2] + second[2] + third[2], snapshot)
        self.assertEqual((second[1], third[1]), (7, 6))
        self.assertEqual(len(m.heap_queries), queries, "continuation reads must not recapture state")
        self.assertEqual(m.read_info(20, 20), (0, 0, b""))
        self.assertEqual(m.read_info(21, 20), (7, 0, b""))
        self.assertEqual(len(m.heap_queries), queries)
        self.assertEqual(m.read_info(0, 20)[2][:2], b"01", "a new offset-zero read selects the next page")
        self.assertEqual(len(m.heap_queries), queries + 1)

    def test_diagnostic_fallback_keeps_all_six_native_arguments_and_usage_runs_factory_callback(self):
        m = self.machine(); m.configure_attribute(uuid=0x2A28)
        arguments = []
        def original(machine):
            arguments.append(tuple(machine.argument(i) for i in range(6)))
            machine.emu.mem_write(machine.argument(3), b"\0\0")
            machine.ret(0x17, clobber=True)
        m.stub("rc_original_device_info", original)
        self.assertEqual(m.read_info(3, 7), (0x17, 0, b""))
        self.assertEqual(arguments, [(0x2345, ATTR, OUT, LENGTH, 3, 7)])
        usage = self.machine("usage")
        usage.configure_attribute()
        usage.emu.mem_write(HW, b"FACTORY-HW\0")
        # Unicorn 2.1.4 loses IT-loop flags in stock memcpy's unaligned path
        # when ANY MEM_WRITE hook exists (even an empty callback). Execute
        # this unchanged factory routine without that hook and audit its
        # complete RAM footprint afterward. Adapter/core guards stay active.
        usage.emu.hook_del(usage.write_guard)
        before = bytes(usage.emu.mem_read(0x20000000, 0x10000))
        self.assertEqual(usage.read_info(0, 20), (0, 10, b"FACTORY-HW"))
        self.assertEqual(usage.heap_queries, [])
        self.assertEqual(usage.read_info(2, 4), (0, 4, b"CTOR"))
        self.assertEqual(bytes(usage.emu.mem_read(HW, 11)), b"FACTORY-HW\0")
        after = bytes(usage.emu.mem_read(0x20000000, 0x10000))
        allowed = [(OUT, OUT + 128), (LENGTH, LENGTH + 4), (STACK - 0x1000, STACK + 32)]
        for index, (a, b) in enumerate(zip(before, after)):
            if a != b:
                at = 0x20000000 + index
                self.assertTrue(any(start <= at < end for start, end in allowed), hex(at))


if __name__ == "__main__":
    unittest.main()
