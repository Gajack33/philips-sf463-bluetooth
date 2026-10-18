"""Real Thumb deferred admission and suspended native-drain regressions.

RTOS events are explicit coalescing API fixtures, not a scheduler model.
The actual4C2A/4D22 dispatcher,4770 drain and4EF4 send path remain executable.
Native ROM/API seams and their deeper stack costs are not qualified here.
"""
from pathlib import Path
import struct
import tempfile
import unittest

from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7

from test_adapter_runtime import RuntimeMachine, StateView, native, APP, HID, INPUT, STACK
from test_adapter_initialization import ALLOC, QUEUE, HW, decoder

MESSAGE, STATUS = INPUT + 128, INPUT + 160
HID_STACK = STACK - 0x600


class AdmissionMachine(RuntimeMachine):
    def __init__(self, compiled, case):
        super().__init__(compiled, case)
        self.write(HID + 0x0E, b"\0")
        self.write(HID + 0x11, b"\xff")
        self.write(APP + 0x0F, b"\x01")
        self.write(APP + 0x17, b"\xff")
        self.write32(HID + 0x28, APP + 0x180)
        self.write32(APP + 0x180, 0x226D)
        self.write32(APP + 0x184, 0x22B9)
        self.write32(APP + 0x188, 0)
        self.pending, self.native_tails, self.profile_callbacks = 0, 0, []
        self.outstanding_blocks, self.maximum_blocks = 0, 0
        self.minimum_sp, self.api_stack_depths = STACK, {}
        self.stub(0x2AE6, self.native_tail)
        self.stub(0x6B4, self.profile_callback)
        self.stub(0x80, lambda m: self.outside(m))
        self.stub(0x116, lambda m: self.outside(m, 1))
        self.stub(0x73D2, lambda m: self.outside(m))

    def _instruction(self, emu, address, size, data):
        if hasattr(self, "minimum_sp"):
            sp = emu.reg_read(UC_ARM_REG_SP)
            self.minimum_sp = min(self.minimum_sp, sp)
            if address in (0x26EE, 0x34B8, 0x2D54, 0x2C3E, 0x4668, 0x35D4):
                self.api_stack_depths[address] = max(self.api_stack_depths.get(address, 0), self.stack_origin - sp)
        return super()._instruction(emu, address, size, data)

    @property
    def stack_origin(self):
        return getattr(self, "origin", STACK)

    def post(self, m):
        super().post(m)
        # Arguments have been clobbered by ret(); use the captured API record.
        semaphore, bits = self.events[-1]
        if semaphore == self.read32(APP + 0x2C):
            self.pending |= bits

    def native_tail(self, m):
        self.native_tails += 1
        self.outside(m)

    def profile_callback(self, m):
        self.profile_callbacks.append(tuple(m.argument(i) for i in range(3)))
        self.outside(m)

    def allocate(self, m):
        if self.allocate_result:
            self.outstanding_blocks += 1
            self.maximum_blocks = max(self.maximum_blocks, self.outstanding_blocks)
            self.case.assertEqual(self.outstanding_blocks, 1, "Only one runtime block may be alive")
        super().allocate(m)

    def free(self, m):
        if m.argument(0) == ALLOC:
            self.case.assertEqual(self.outstanding_blocks, 1)
            self.outstanding_blocks -= 1
        super().free(m)

    def peer_get(self, m):
        if m.argument(0) == 0x30E:
            self.case.assertEqual(self.depth, 0)
            m.write(m.argument(1), struct.pack("<H", 0x2345))
            m.ret(0, clobber=True)
        else:
            super().peer_get(m)

    def message(self, kind, phase, status=0, entry=0x4C2A):
        self.write(STATUS, bytes([status]))
        self.write(MESSAGE, struct.pack("<HBBI", kind, phase, 0, STATUS))
        #4C2A is entered from HID main480A, with its permanent32-byte frame.
        self.seed()
        self.emu.reg_write(UC_ARM_REG_SP, HID_STACK - 32)
        self.emu.reg_write(native.UC_ARM_REG_R0, MESSAGE)
        self.minimum_sp, self.origin, self.api_stack_depths = HID_STACK, HID_STACK, {}
        saved = [self.emu.reg_read(r) for r in native.REGISTERS[4:12]]
        self.run(entry)
        self.case.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), HID_STACK - 32)
        self.case.assertEqual([self.emu.reg_read(r) for r in native.REGISTERS[4:12]], saved)
        self.case.assertEqual(self.depth, 0)
        self.origin = STACK

    def turn(self, mask=None):
        if mask is None:
            mask = self.pending & struct.unpack_from("<I", self.image, 0x22B4)[0]
            self.pending &= ~mask
        self.seed()
        self.emu.reg_write(UC_ARM_REG_R5, mask)
        before = [self.emu.reg_read(r) for r in native.REGISTERS[4:12]]
        self.minimum_sp, self.origin, self.api_stack_depths = STACK, STACK, {}
        self.run(0x1796, 0x179A)
        self.case.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), STACK)
        self.case.assertEqual([self.emu.reg_read(r) for r in native.REGISTERS[4:12]], before)
        self.case.assertEqual(self.depth, 0)

    def arm_last_native_report(self):
        # Native5006 selects slot1 from index0, then4788 publishes index1.
        self.write(HID + 0x0E, b"\x01")
        self.write(HID + 0x13, b"\x01")
        self.write(HID + 0x14, b"\0\x01")
        data = b"\x45\0\0"
        self.write(QUEUE + 12, bytes([2, 1, 3]) + data + bytes(6))
        self.seed()
        self.emu.reg_write(UC_ARM_REG_SP, HID_STACK - 32)
        self.emu.reg_write(UC_ARM_REG_R5, 4)
        self.emu.reg_write(UC_ARM_REG_R6, HID)
        self.emu.reg_write(UC_ARM_REG_R7, QUEUE)
        return data


class DeferredAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-deferred-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled = {}
        for variant in ("diagnostic", "usage"):
            directory = Path(cls.temporary.name) / variant
            directory.mkdir()
            cls.compiled[variant] = native.compile_integration(directory, variant)

    def machine(self, variant="diagnostic"):
        return AdmissionMachine(self.compiled[variant], self)

    def boot_without_bond(self, m):
        m.bond_count = 0
        m.checked_call("rc_app_init")
        self.assertEqual((m.native_init_count, m.allocations), (1, []))
        self.assertEqual(m.checked_call("rc_enabled"), 0)

    def test_boot_without_bond_admits_after_connection_event_and_neutralizes_both_reports(self):
        m = self.machine(); self.boot_without_bond(m)
        m.bond_count = 1; m.write(HID + 0x0D, b"\x01")
        m.message(1, 6)
        self.assertEqual(m.pending, 0x400)
        self.assertEqual(m.allocations, [], "HID callback must only schedule APP admission")
        m.turn()
        self.assertEqual((m.native_init_count, m.native_tails, m.allocations), (1, 1, [640]))
        self.assertEqual(m.read32(QUEUE), 0x53465243)
        self.assertEqual(m.read32(QUEUE + 4), ALLOC)
        self.assertEqual(m.read_state().core.repair_mask, 3)
        self.assertEqual(m.read_state().pending_rear_index, 255)
        m.write(HID + 0x0E, b"\x01"); m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [(1, bytes(8)), (2, bytes(3))])

    def test_pairing_success_while_native_tx_ready_waits_for_next_connection_not_a_timer(self):
        m = self.machine(); self.boot_without_bond(m)
        snapshot, queue = m.read(HW, 21), m.read(QUEUE, 36)
        m.bond_count = 1; m.message(8, 1)
        self.assertEqual(m.pending, 0x400)
        self.assertEqual(m.read(HID + 0x0E, 1), b"\x01")
        m.turn(); m.turn(0x100); m.turn(0x200); m.turn(0x80)
        self.assertEqual(m.allocations, [])
        self.assertEqual(m.read(QUEUE, 36), queue)
        latest = m.read(HW, 21)
        self.assertNotEqual(latest, snapshot)
        fallback = decoder.decode_pages("6.097", [latest[:20].decode()])["fallback"]
        self.assertEqual(fallback["reason_code"], 11)
        self.assertEqual(fallback["snapshot_scope"], "latest_deferred_admission_refusal")
        self.assertTrue(fallback["flags"]["deferred_admission"])
        self.assertIsNone(fallback["heap"])
        m.turn(0x100); m.turn(0x200)
        self.assertEqual(m.read(HW, 21), latest, "Ordinary wakes must not rewrite refusal provenance")
        m.write(HID + 0x0D, b"\x05"); m.message(1, 6); m.turn()
        self.assertEqual(m.allocations, [640])
        self.assertEqual(m.native_init_count, 1)

    def test_only_changed_successful_lifecycle_events_post_the_coalesced_admission_bit(self):
        m = self.machine(); self.boot_without_bond(m)
        m.write(HID + 0x0D, b"\x01")
        m.message(1, 6); m.message(1, 6)
        self.assertEqual([event for event in m.events if event[1] == 0x400],
                         [(m.read32(APP + 0x2C), 0x400)])
        for phase, status in ((0, 0), (1, 1), (1, 0), (2, 0), (2, 0)):
            m.message(8, phase, status)
        # Failed COMPLETE stores phase1 too. Repeating that same phase does
        # not create a transition; successful phase2 remains a useful event.
        self.assertEqual(len([event for event in m.events if event[1] == 0x400]), 2)
        self.assertEqual(m.pending & 0x400, 0x400)
        m.write(HID + 0x0E, b"\0"); m.turn()
        self.assertEqual(m.native_tails, 1)
        self.assertEqual(m.allocations, [])  # Still no saved bond.
        self.assertEqual(m.pending & 0x400, 0)

    def test_ordinary_wakes_and_active_reentrant_events_never_allocate_again(self):
        m = self.machine(); self.boot_without_bond(m)
        m.checked_call("rc_rear_callback", 0, INPUT)
        m.checked_call("rc_front_callback", 0, INPUT, 0)
        m.checked_call("rc_timer_callback")
        m.checked_call("rc_event_drain")
        for mask in (0, 0x40, 0x80, 0x100, 0x200, 0x80000000):
            m.turn(mask)
        self.assertEqual((m.heap_queries, m.allocations), ([], []))
        m.bond_count = 1
        allocate = m.stubs[0x2C3E]
        def event_during_allocate(machine):
            # HID may post another useful event while APP waits in an API;
            # it cannot invoke admission or recursively allocate from HID.
            m.pending |= 0x400
            allocate(machine)
        m.stub(0x2C3E, event_during_allocate)
        m.turn(0x400); m.turn(); m.turn(0x400)
        self.assertEqual((m.native_init_count, m.allocations, m.frees), (1, [640], []))
        self.assertEqual(len(m.heap_queries), 2)
        self.assertEqual(m.read32(QUEUE + 4), ALLOC)
        self.assertEqual((m.outstanding_blocks, m.maximum_blocks), (1, 1))

    def test_unknown_native_pending_rear_press_is_released_without_replay_after_admission(self):
        m = self.machine(); self.boot_without_bond(m); m.bond_count = 1
        m.write(APP + 0x17, b"\x26")
        m.write(APP + 0x20, b"\x80\0")
        m.turn(0x400)
        self.assertEqual(m.read(APP + 0x17, 1), b"\x26")
        m.checked_call("rc_event_drain")
        self.assertEqual(m.read(APP + 0x17, 1), b"\xff")
        self.assertEqual(m.decoded, [], "A pre-admission press has no source timestamp/session")
        m.write(HID + 0x0E, b"\x01"); m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [(1, bytes(8)), (2, bytes(3))])

    def test_final_quiescence_guard_preserves_a_real_last_report_suspended_before_copy(self):
        for boundary in ("before-query", "after-precheck"):
            with self.subTest(boundary=boundary):
                m = self.machine(); self.boot_without_bond(m); m.bond_count = 1
                snapshot = m.read(HW, 21)
                allocate = m.stubs[0x2C3E]
                if boundary == "after-precheck":
                    m.stub(0x2C3E, lambda machine: machine.emu.emu_stop())
                    m.seed(); m.emu.reg_write(native.UC_ARM_REG_R0, 0x400)
                    m.stop = native.RETURN
                    m.emu.emu_start(m.address("rc_app_turn") | 1, 0, count=250000)
                    self.assertEqual(m.emu.reg_read(UC_ARM_REG_PC), 0x2C3E)
                    app_context = m.emu.context_save()
                data = m.arm_last_native_report()
                native_parameters = m.stubs[0x35D4]
                m.stub(0x35D4, lambda machine: machine.emu.emu_stop())
                m.stop = 0x47AA
                m.emu.emu_start(0x476D, 0, count=250000)
                self.assertEqual(m.emu.reg_read(UC_ARM_REG_PC), 0x35D4)
                self.assertEqual(m.read(HID + 0x14, 2), b"\x01\x01")
                queue = m.read(QUEUE, 36)
                hid_context = m.emu.context_save()
                if boundary == "after-precheck":
                    m.emu.context_restore(app_context); m.stub(0x2C3E, allocate)
                    m.run(0x2C3E)
                    self.assertEqual((m.allocations, m.frees), ([640], [ALLOC]))
                else:
                    m.turn(0x400)
                    self.assertEqual((m.allocations, m.frees), ([], []))
                self.assertEqual(m.read(QUEUE, 36), queue)
                latest = m.read(HW, 21)
                self.assertNotEqual(latest, snapshot)
                fallback = decoder.decode_pages("6.097", [latest[:20].decode()])["fallback"]
                self.assertEqual(fallback["reason_code"], 11)
                self.assertEqual(fallback["snapshot_scope"], "latest_deferred_admission_refusal")
                if boundary == "before-query":
                    self.assertIsNone(fallback["heap"])
                else:
                    self.assertEqual(fallback["heap"]["sample_phase"], "post_allocation_before_release")
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                m.emu.context_restore(hid_context); m.stub(0x35D4, native_parameters)
                m.run(0x35D4, 0x47AA)
                self.assertEqual(m.notifications, [(2, data)])
                self.assertEqual(m.read(QUEUE, 36), queue)
                self.assertEqual(m.emu.reg_read(UC_ARM_REG_SP), HID_STACK - 32)

    def test_retry_refusals_record_latest_reason_and_phase_without_changing_legacy_or_querying_on_reads(self):
        for condition, reason in (("no-semaphore", 1), ("two-bonds", 2), ("zero-peer", 4), ("rpc", 3),
                                  ("total", 5), ("largest", 6), ("null", 7), ("reserve", 8),
                                  ("queue", 9), ("mailbox", 10)):
            with self.subTest(condition=condition):
                m = self.machine(); self.boot_without_bond(m)
                snapshot, queue = m.read(HW, 21), m.read(QUEUE, 36)
                m.bond_count = 1
                if condition == "no-semaphore": m.write32(HID + 0x1C, 0)
                if condition == "two-bonds": m.bond_count = 2
                if condition == "zero-peer": m.saved_peer = bytes(6)
                if condition == "rpc": m.bond_status = 1
                if condition == "total": m.free_before = 1415
                if condition == "largest": m.largest = 639
                if condition == "null": m.allocate_result = 0
                if condition == "reserve": m.free_after = 767
                if condition == "queue": m.write(HID + 0x14, b"\0\x01")
                if condition == "mailbox": m.write(APP + 0x20, b"\x10\0")
                m.turn(0x400)
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                self.assertEqual(m.read(QUEUE, 36), queue)
                latest = m.read(HW, 21)
                self.assertNotEqual(latest, snapshot)
                fallback = decoder.decode_pages("6.097", [latest[:20].decode()])["fallback"]
                self.assertEqual(fallback["reason_code"], reason)
                self.assertEqual(fallback["snapshot_scope"], "latest_deferred_admission_refusal")
                self.assertTrue(fallback["flags"]["deferred_admission"])
                if reason < 5:
                    self.assertIsNone(fallback["heap"])
                else:
                    self.assertEqual(fallback["heap"]["sample_phase"],
                                     "pre_allocation" if reason < 8 else "post_allocation_before_release")
                    self.assertEqual(fallback["heap"]["free_bytes"],
                                     m.free_before if reason < 8 else m.free_after)
                queries, allocations = len(m.heap_queries), list(m.allocations)
                old_count, old_rpc = m.stubs[0x26EE], m.stubs[0x34B8]
                def no_query(machine): self.fail("GATT fallback reads must not perform bond/RPC queries")
                m.stub(0x26EE, no_query); m.stub(0x34B8, no_query); m.configure_attribute()
                self.assertEqual([m.read_info()[2] for _ in range(3)], [latest[:20]] * 3)
                self.assertEqual((len(m.heap_queries), m.allocations), (queries, allocations))
                m.stub(0x26EE, old_count); m.stub(0x34B8, old_rpc)
                queries = len(m.heap_queries)
                m.turn(0x100); m.turn(0x200)
                self.assertEqual(len(m.heap_queries), queries)
                self.assertEqual(m.read(HW, 21), latest)
                self.assertEqual(m.native_init_count, 1)
                self.assertEqual(m.outstanding_blocks, 0)
                m.bond_count, m.bond_status, m.saved_peer = 1, 0, bytes([1,2,3,4,5,6])
                m.free_before, m.free_after, m.largest, m.allocate_result = 3000, 2400, 2500, ALLOC
                m.write32(HID + 0x1C, 0x20006200)
                m.write(HID + 0x14, b"\0\0"); m.write(APP + 0x20, b"\0\0")
                m.write(HID + 0x0D, b"\x01"); m.message(1, 6); m.turn()
                self.assertEqual(m.checked_call("rc_enabled"), 1)
                self.assertEqual((m.outstanding_blocks, m.maximum_blocks), (1, 1))
                self.assertEqual(m.native_init_count, 1)

    def test_quiescence_reason_round_trips_and_usage_preserves_factory_hardware_bytes(self):
        for variant in ("diagnostic", "usage"):
            m = self.machine(variant)
            factory = b"FACTORY-HARDWARE-REV\0"; m.write(HW, factory)
            m.write(HID + 0x0E, b"\x01"); m.checked_call("rc_app_init")
            self.assertEqual((m.allocations, m.heap_queries), ([], []))
            if variant == "diagnostic":
                fallback = decoder.decode_pages("6.097", [m.read(HW, 20).decode()])["fallback"]
                self.assertEqual(fallback["reason"], "native_transmission_not_quiescent")
                self.assertEqual(fallback["snapshot_scope"], "latest_boot_admission_refusal")
                self.assertFalse(fallback["flags"]["deferred_admission"])
                self.assertIsNone(fallback["bond_count"]); self.assertIsNone(fallback["heap"])
            else:
                self.assertEqual(m.read(HW, 21), factory)
            m.turn(0x400)
            self.assertEqual(m.allocations, [])
            if variant == "usage": self.assertEqual(m.read(HW, 21), factory)
            m.write(HID + 0x0E, b"\0"); m.turn(0x400)
            self.assertEqual(m.allocations, [640])
            if variant == "usage": self.assertEqual(m.read(HW, 21), factory)

    def test_each_new_useful_transition_updates_last_refusal_and_success_enables_active_pages(self):
        m = self.machine(); self.boot_without_bond(m)
        def current():
            return decoder.decode_pages("6.097", [m.read(HW, 20).decode()])["fallback"]
        self.assertEqual(current()["snapshot_scope"], "latest_boot_admission_refusal")
        m.write(HID + 0x0D, b"\x01"); m.message(1, 6); m.turn()
        self.assertEqual((current()["reason_code"], current()["snapshot_scope"]),
                         (2, "latest_deferred_admission_refusal"))
        m.bond_count = 1; m.message(8, 1); m.turn()
        self.assertEqual(current()["reason_code"], 11)
        m.free_before = 1415
        m.write(HID + 0x0D, b"\x05"); m.message(1, 6); m.turn()
        self.assertEqual((current()["reason_code"], current()["heap"]["sample_phase"]),
                         (5, "pre_allocation"))
        m.free_before = 3000
        m.write(HID + 0x0D, b"\x05"); m.message(1, 6); m.turn()
        self.assertEqual((m.allocations, m.native_init_count), ([640], 1))
        self.assertEqual(m.read(HW, 1), b"\0", "A successful claim invalidates previous refusal provenance")
        m.configure_attribute()
        captured = [m.read_info()[2].decode() for _ in range(3)]
        self.assertTrue(decoder.decode_pages("6.097", captured)["improvements_active"])

    def test_boot_quiescence_change_after_allocation_records_actual_final_sample(self):
        m = self.machine()
        allocate = m.stubs[0x2C3E]
        def readiness_changed(machine):
            m.write(HID + 0x0E, b"\x01")
            allocate(machine)
        m.stub(0x2C3E, readiness_changed)
        queue = m.read(QUEUE, 36)
        m.checked_call("rc_app_init"); m.configure_attribute()
        captured = m.read_info()[2].decode()
        fallback = decoder.decode_pages("6.097", [captured])["fallback"]
        self.assertEqual(fallback["reason"], "native_transmission_not_quiescent")
        self.assertEqual(fallback["bond_count"], 1)
        self.assertEqual(fallback["heap"], {"free_bytes": 2400, "largest_free_block_bytes": 2400,
                                         "sample_phase": "post_allocation_before_release"})
        self.assertEqual((m.allocations, m.frees), ([640], [ALLOC]))
        self.assertEqual(m.read(QUEUE, 36), queue)

    def test_corrupt_existing_claim_is_fail_closed_and_does_not_leak_a_second_block(self):
        m = self.machine(); self.boot_without_bond(m); m.bond_count = 1
        m.write32(QUEUE, 0x53465243); m.write32(QUEUE + 4, 3)
        queue = m.read(QUEUE, 36)
        m.turn(0x400)
        self.assertEqual((m.allocations, m.heap_queries), ([], []))
        self.assertEqual(m.read(QUEUE, 36), queue)

    def test_new_native_frames_fit_existing_task_budgets_at_the_explicit_api_seams(self):
        measurements = []
        for kind, phase, status in ((1, 6, 0), (8, 0, 0), (8, 1, 0), (8, 1, 1), (8, 2, 0)):
            pair=[]
            for entry in ("rc_original_hid_message", 0x4C2A):
                m = self.machine(); self.boot_without_bond(m)
                m.write(HID + 0x0D, b"\x01")
                m.message(kind, phase, status, entry)
                prefix = HID_STACK - m.minimum_sp
                self.assertLessEqual(prefix, 400)
                pair.append((prefix, dict(m.api_stack_depths)))
            useful = (kind == 1 or (phase in (1, 2) and status == 0))
            self.assertLessEqual(pair[1][0] - pair[0][0], 16)
            if not useful:
                self.assertEqual(pair[1], pair[0], "Unrelated/failed events must tail-call native without a held frame")
            for address, depth in pair[0][1].items():
                self.assertLessEqual(pair[1][1][address] - depth, 16)
            measurements.append((kind, phase, status, pair))
        m = self.machine(); self.boot_without_bond(m); m.bond_count = 1
        m.turn(0x400)
        self.assertLessEqual(STACK - m.minimum_sp + 24, 750)  # NativeAPP permanent frame.
        self.assertEqual(m.native_init_count, 1)
        self.assertEqual(len(measurements), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
