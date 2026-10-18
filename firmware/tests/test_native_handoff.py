"""Real native slot-to-stack handoff; bounded API pauses model task switches.

No radio/RTOS scheduling, ROM stack bound or hardware wake is qualified here.
Only the HID drain snapshots legacy slots; admission stays in APP.
"""
import struct
import tempfile
import unittest

from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7

from test_deferred_admission import AdmissionMachine, HID_STACK
from test_adapter_runtime import native, APP, HID
from test_adapter_initialization import ALLOC, QUEUE
from test_native_dispatch import DispatchMachine, UART


class HandoffMachine(AdmissionMachine):
    @staticmethod
    def allowed_ranges():
        # Exact native2170 attempted-report cache, resolved by literal2B08;
        # keep the same3B bound as the native-dispatch comparison fixture.
        return AdmissionMachine.allowed_ranges() + [(0x20001789, 0x2000178C)]

    def __init__(self, compiled, case):
        self.observers, self.copies = {}, []
        super().__init__(compiled, case)

    def _instruction(self, emu, address, size, data):
        if address in self.observers:
            self.observers[address](self)
        if address == 0x21C:
            self.copies.append(tuple(self.argument(i) for i in range(3)))
        return super()._instruction(emu, address, size, data)

    def generic(self, m):
        if m.argument(2) == 0x40E:  # Native5068's stored-bond count RPC.
            self.case.assertEqual(self.depth, 0)
            self.case.assertEqual((m.argument(0), m.argument(1)), (0x10, 0x134B9))
            m.write(m.argument(3), bytes([self.bond_count]))
            m.ret(0, clobber=True)
            return
        return super().generic(m)

    def fallback(self):
        self.bond_count = 0
        self.checked_call("rc_app_init")
        self.case.assertEqual(self.checked_call("rc_enabled"), 0)
        self.bond_count = 1
        return self

    def real_inputs(self):
        self.stubs.pop(0x1DAC); self.stubs.pop(0x1FDA)
        self.native_services, self.baseline = [], False
        for address, count in ((0x2874, 1), (0x2812, 1), (0x270C, 0),
                               (0x53DA, 3), (0x5A1A, 3), (0x598C, 0), (0x40B4, 3)):
            self.stub(address, lambda m, a=address, n=count: DispatchMachine.service(self, m, a, n))
        self.stub(0x280C, lambda m: self.outside(m, 0))
        self.write(APP + 0x0F, b"\x06"); self.write(APP + 0x12, b"\x05")
        DispatchMachine.configure_rear(self)
        return self

    def source_front(self, index=None, special=0):
        self.write(native.INPUT, bytes([index or 0]))
        self.checked_call(0x1ABC, 0 if index is None else 1, native.INPUT, special)
        self.checked_call(0x1878)

    def source_rear(self, index=None):
        self.write(native.INPUT, bytes([index or 0]))
        self.checked_call(0x1A90, 0 if index is None else 1, native.INPUT)
        self.checked_call(0x1878)

    def enter_hid(self):
        self.seed()
        self.emu.reg_write(UC_ARM_REG_SP, HID_STACK - 32)
        self.emu.reg_write(UC_ARM_REG_R5, 4)
        self.emu.reg_write(UC_ARM_REG_R6, HID)
        self.emu.reg_write(UC_ARM_REG_R7, QUEUE)
        self.minimum_sp, self.origin, self.api_stack_depths = HID_STACK, HID_STACK, {}
        self.saved = [self.emu.reg_read(r) for r in native.REGISTERS[4:12]]

    def arm(self, head=0, length=3, report=2):
        self.write(HID + 0x0E, b"\x01")
        self.write(HID + 0x13, b"\x01")
        next_index = (head + 1) % 3
        self.write(HID + 0x14, bytes([head, next_index]))
        data = bytes(range(0x41, 0x41 + min(length, 9)))
        slot = bytes([report, 1, length]) + data + bytes(9 - len(data))
        self.write(QUEUE + next_index * 12, slot)
        self.seed()
        self.emu.reg_write(UC_ARM_REG_SP, HID_STACK - 32)
        self.emu.reg_write(UC_ARM_REG_R5, 4)
        self.emu.reg_write(UC_ARM_REG_R6, HID)
        self.emu.reg_write(UC_ARM_REG_R7, QUEUE)
        self.minimum_sp, self.origin, self.api_stack_depths = HID_STACK, HID_STACK, {}
        self.saved = [self.emu.reg_read(r) for r in native.REGISTERS[4:12]]
        return slot, data

    def assert_hid_return(self):
        self.case.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), HID_STACK - 32)
        self.case.assertEqual([self.emu.reg_read(r) for r in native.REGISTERS[4:12]], self.saved)
        self.case.assertEqual(self.depth, 0)

    def other_task_call(self, entry, stack, *args):
        self.seed(); self.emu.reg_write(UC_ARM_REG_SP, stack)
        saved = [self.emu.reg_read(r) for r in native.REGISTERS[4:12]]
        for reg, value in zip(native.ARGUMENTS, args): self.emu.reg_write(reg, value)
        self.run(entry)
        self.case.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), stack)
        self.case.assertEqual([self.emu.reg_read(r) for r in native.REGISTERS[4:12]], saved)
        self.case.assertEqual(self.depth, 0)


class NativeHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-native-handoff-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled = native.compile_integration(cls.temporary.name)

    def machine(self):
        return HandoffMachine(self.compiled, self).fallback()

    def test_release_only_consumer_action_keeps_native_attempt_dedupe_across_initial_neutrals(self):
        for attempted in (0, 0x30, 0x41):
            with self.subTest(attempted=attempted):
                old = DispatchMachine(self.compiled, self, baseline=True)
                m = self.machine().real_inputs()
                for machine in (old, m):
                    machine.write(APP + 0x0F, b"\x02"); machine.write(APP + 0x12, b"\x03")
                    if machine is old: machine.front(0x14)
                    else: machine.source_front(0x14)
                    self.assertEqual(machine.read(APP + 0x19, 1), b"\x02")
                    self.assertEqual(machine.notifications, [])
                    machine.write(0x20003044, struct.pack("<H", attempted))
                    machine.write(APP + 0x0F, b"\x06"); machine.write(APP + 0x12, b"\x05")
                old.front()
                expected = [0] if attempted == 0x41 else [0x41, 0]
                self.assertEqual(old.usages(), expected)
                m.write(HID + 0x0E, b"\x01"); m.turn(0x400)
                self.assertEqual(m.checked_call("rc_enabled"), 1)
                self.assertEqual(m.read_state().handoff_mask & 2, 2 if attempted == 0x41 else 0)
                m.checked_call("rc_hid_worker")
                m.notifications.clear()
                m.source_front(); m.checked_call("rc_hid_worker")
                observed = [int.from_bytes(data[:2], "little") for report, data in m.notifications if report == 2]
                # A duplicate neutral may be suppressed by the new queue. The
                # release-only non-neutral action must match actual06.07.
                self.assertEqual([x for x in observed if x], [x for x in expected if x])
                self.assertEqual(m.read_state().handoff_mask & 2, 0)
                m.source_front(0); m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(sum(report == 2 and data == b"\x30\0\0" for report, data in m.notifications), 1)

    def test_pending_voice_tap_preserves_native_attempt_dedupe_without_a_voice_exception(self):
        for attempted in (0, 0x221):
            with self.subTest(attempted=attempted):
                old = DispatchMachine(self.compiled, self, baseline=True)
                # Audio parameter delivery is an explicit peripheral seam;
                # pending selection19D4 and both serializers remain native.
                m = self.machine().real_inputs()
                audio = {old: [], m: []}
                def audio_parameter(machine):
                    audio[machine].append((machine.argument(0), machine.argument(1),
                                           machine.read(machine.argument(2), 1)))
                    machine.outside(machine, 0)
                for machine in (old, m): machine.stub(0x40B4, audio_parameter)
                m.write(APP + 0x0F, b"\x02"); m.write(APP + 0x12, b"\x03")
                m.source_front(4)
                self.assertEqual(m.read(APP + 0x11, 1), b"\x01")
                self.assertEqual(int.from_bytes(m.read(APP + 0x20, 2), "little") & 0x400, 0x400)
                self.assertEqual(m.notifications, [])
                m.write(0x20003044, struct.pack("<H", attempted))
                old.write(APP + 0x0F, b"\x02"); old.write(APP + 0x12, b"\x03")
                old.front(4)
                old.write(0x20003044, struct.pack("<H", attempted))
                old.write(APP + 0x0F, b"\x06"); old.write(APP + 0x12, b"\x05")
                old.checked_call(0x1878)
                self.assertEqual([usage for usage in old.usages() if usage], [] if attempted else [0x221])
                m.write(APP + 0x0F, b"\x06"); m.write(APP + 0x12, b"\x05")
                m.write(HID + 0x0E, b"\x01"); m.turn(0x400)
                self.assertEqual(m.read_state().handoff_mask & 2, 2 if attempted == 0x221 else 0)
                m.checked_call("rc_hid_worker"); m.notifications.clear()
                m.checked_call(0x1878); m.checked_call("rc_hid_worker")
                voices = [data for report, data in m.notifications if report == 2 and data[:2] == b"\x21\x02"]
                self.assertEqual(len(voices), 0 if attempted == 0x221 else 1)
                self.assertEqual(m.read(APP + 0x11, 1), b"\0")
                self.assertEqual(audio[m], [(2, 1, b"\x08")])
                self.assertEqual(audio[m], audio[old])
                m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(m.read_state().handoff_mask & 2, 0)

    def test_first_fresh_press_before_initial_neutrals_is_not_lost_or_duplicated(self):
        m = self.machine().real_inputs()
        m.write(HID + 0x0E, b"\x01"); m.turn(0x400)
        self.assertEqual(m.read_state().handoff_mask & 3, 0)
        m.source_front(0)
        m.checked_call("rc_hid_worker")
        m.source_front(0); m.checked_call("rc_hid_worker")
        self.assertEqual(sum(report == 2 and data == b"\x30\0\0" for report, data in m.notifications), 1)
        m.source_front(); m.checked_call("rc_hid_worker")

    def test_only_real_rear_release_can_resolve_stale_sentinel_at_successful_claim(self):
        for release in (None, 255):
            with self.subTest(release=release):
                m = self.machine().real_inputs()
                m.write(HID + 0x0E, b"\x01"); m.write(HID + 0x13, b"\x01")
                m.source_rear(2)
                cache = m.read(0x20001789, 3)
                self.assertEqual(cache, b"\x04\0\0")
                m.turn(0x400)
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                self.assertEqual(m.allocations, [])
                m.write(UART + 9, b"\0")
                m.source_rear(release)
                self.assertEqual(m.checked_call("rc_enabled"), 1)
                self.assertEqual((m.read(APP + 0x1B, 1), m.read(APP + 0x17, 1)), (b"\xff", b"\xff"))
                self.assertEqual(m.read(0x20001789, 3), cache,
                    "A proven release repairs only source sentinels, never an attempted/accepted cache")
                self.assertEqual(bytes(m.read_state().core.accepted), bytes(16))
                self.assertEqual(m.read_state().handoff_mask & 3, 0)
                m.checked_call("rc_hid_worker"); m.notifications.clear()
                m.write(UART + 9, b"\x01")
                m.source_rear(2); m.source_rear(); m.checked_call("rc_hid_worker")
                self.assertEqual(m.notifications, [(1, b"\0\0\x04\0\0\0\0\0"), (1, bytes(8))])
                self.assertEqual(m.allocations, [640])

    def test_failed_rear_release_admission_preserves_native_fallback_sentinels_and_cache(self):
        for refusal in ("bond", "heap", "malloc"):
            for release in (None, 255):
                with self.subTest(refusal=refusal, release=release):
                    m = self.machine().real_inputs()
                    m.write(HID + 0x0E, b"\x01"); m.write(HID + 0x13, b"\x01")
                    m.source_rear(2); m.write(UART + 9, b"\0")
                    cache = m.read(0x20001789, 3)
                    if refusal == "bond": m.bond_count = 0
                    elif refusal == "heap": m.free_before = 1415
                    else: m.allocate_result = 0
                    m.source_rear(release)
                    self.assertEqual(m.checked_call("rc_enabled"), 0)
                    self.assertEqual(m.read(APP + 0x1B, 1), b"\x02")
                    self.assertEqual(m.read(APP + 0x17, 1), b"\x02" if release is None else b"\xff")
                    self.assertEqual(m.read(0x20001789, 3), cache)
                    counts = (len(m.allocations), len(m.heap_queries))
                    m.source_rear(2); m.checked_call("rc_timer_callback"); m.turn(0x80)
                    self.assertEqual((len(m.allocations), len(m.heap_queries)), counts,
                                     "A press, pending replay or timer must not retry admission")

    def test_shared_or_replay_mailbox_cannot_supply_rear_release_proof(self):
        for mask in (0x11, 0x90, 0x91):
            with self.subTest(mask=mask):
                m = self.machine().real_inputs()
                m.write(HID + 0x0E, b"\x01"); m.write(HID + 0x13, b"\x01")
                m.source_rear(2); m.write(UART + 9, b"\0")
                m.write(APP, b"\x01\xff"); m.write(APP + 6, b"\0")
                m.write(APP + 0x20, struct.pack("<H", mask))
                m.checked_call(0x1878)
                self.assertEqual(m.checked_call("rc_enabled"), 0)
                self.assertEqual(m.allocations, [])
                self.assertEqual(m.read(APP + 0x1B, 1), b"\x02")

    def test_new_rear_mailbox_published_during_release_admission_prevents_stale_claim(self):
        m = self.machine().real_inputs()
        m.write(HID + 0x0E, b"\x01"); m.write(HID + 0x13, b"\x01")
        m.source_rear(2); m.write(UART + 9, b"\0")
        m.write(native.INPUT, b"\xff"); m.checked_call(0x1A90, 1, native.INPUT)
        m.seed(); m.run(0x1878, 0x2C3E)
        context = m.emu.context_save()
        # A whole higher-priority Clock callback while APP waits in malloc.
        # No impossible preemption is inserted inside its pure memcpy.
        m.write(native.INPUT + 32, b"\x03")
        m.checked_call(0x1A90, 1, native.INPUT + 32)
        m.emu.context_restore(context); m.run(0x2C3E)
        self.assertEqual(m.checked_call("rc_enabled"), 0)
        self.assertEqual((m.allocations, m.frees), ([640], [ALLOC]))
        self.assertEqual(m.read(APP + 0x1B, 1), b"\x02")
        self.assertEqual(m.read(APP + 0x20, 2), b"\x10\0")
        self.assertEqual(m.read(APP + 1, 1), b"\x03")

    def held_front_claim(self):
        m = self.machine().real_inputs()
        m.write(HID + 0x0E, b"\x01"); m.write(HID + 0x13, b"\x01")
        m.source_front(0); m.turn(0x400); m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().handoff_mask & 2, 2)
        m.notifications.clear()
        return m

    def test_synthetic_orientation_neutrals_do_not_release_source_held_fence(self):
        m = self.held_front_claim()
        m.source_front(0, special=0xF1); m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().handoff_mask & 2, 2)
        m.source_front(0); m.checked_call("rc_hid_worker")
        self.assertFalse(any(report == 2 and any(data) for report, data in m.notifications))
        m.source_front(); m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().handoff_mask & 2, 0)

    def test_source_overflow_refused_physical_release_lifts_fence_only_after_purge(self):
        for release in (None, 255):
            with self.subTest(release=release):
                m = self.held_front_claim()
                m.write(native.INPUT, b"\0")
                for _ in range(16): m.checked_call(0x1ABC, 1, native.INPUT, 0)
                self.assertEqual(m.read_state().core.source_count, 16)
                m.write(native.INPUT, bytes([release or 0]))
                m.checked_call(0x1ABC, 0 if release is None else 1, native.INPUT, 0)
                self.assertEqual(m.read_state().core.source_barrier, 1)
                self.assertEqual(m.read_state().handoff_mask & 0x22, 0x22)
                m.checked_call("rc_hid_worker")
                self.assertEqual(m.read_state().handoff_mask & 0x22, 0x22)
                m.checked_call(0x1878)
                self.assertEqual(m.read_state().core.source_count, 0)
                self.assertEqual(m.read_state().handoff_mask & 0x22, 0)
                m.source_front(0); m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(sum(report == 2 and data == b"\x30\0\0" for report, data in m.notifications), 1)

    def test_refused_uart_release_fragments_preserve_release_evidence_until_fifo_purge(self):
        for split in range(1, 6):
            with self.subTest(split=split):
                m = self.held_front_claim()
                m.write(native.INPUT, b"\x02")
                for _ in range(17): m.checked_call(0x1A90, 1, native.INPUT)
                self.assertEqual(m.read_state().core.source_barrier, 1)
                frame = bytes.fromhex("fe0001ffffff")
                m.uart_chunks = [frame[:split], frame[split:]]
                m.checked_call(0x551A); m.checked_call(0x551A)
                self.assertEqual(m.read_state().core.parser_count, 0)
                self.assertEqual(m.read_state().handoff_mask & 0x22, 0x22)
                m.checked_call("rc_hid_worker"); m.checked_call(0x1878)
                self.assertEqual(m.read_state().handoff_mask & 0x22, 0)
                m.source_front(0); m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(sum(report == 2 and data == b"\x30\0\0" for report, data in m.notifications), 1)

    def test_popped_front_dispatch_cannot_survive_clock_fifo_overflow_and_worker_repairs(self):
        m = self.machine().real_inputs()
        m.write(HID + 0x0E, b"\x01"); m.turn(0x400); m.checked_call("rc_hid_worker")
        m.notifications.clear()
        m.write(native.INPUT, b"\0"); m.checked_call(0x1ABC, 1, native.INPUT, 0)
        m.seed(); m.run(0x1878, 0x34B8)  # APP popped source, waiting on its419 query.
        self.assertEqual(m.argument(2), 0x419)
        self.assertEqual(m.read_state().dispatch_active, 1)
        app_context = m.emu.context_save()
        m.write(native.INPUT + 32, b"\x02")
        for _ in range(17):
            m.other_task_call(0x1A90, native.STACK - 0xC00, 1, native.INPUT + 32)
        self.assertEqual(m.read_state().core.source_barrier, 1)
        m.other_task_call("rc_hid_worker", HID_STACK - 32)
        self.assertEqual(m.read_state().core.quarantine_mask, 0)
        self.assertEqual(m.notifications, [(1, bytes(8)), (2, bytes(3))])
        m.emu.context_restore(app_context); m.run(0x34B8)
        m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [(1, bytes(8)), (2, bytes(3))],
                         "A pre-overflow popped Power must not be revived after worker neutralization")
        self.assertEqual(m.read_state().core.source_barrier, 0)
        m.source_front(); m.source_front(0); m.source_front(); m.checked_call("rc_hid_worker")
        self.assertEqual(sum(report == 2 and data == b"\x30\0\0" for report, data in m.notifications), 1)

    def test_power_handoff_repeat_is_red_without_source_fence_and_green_with_it(self):
        for disable_fence in (False, True):
            with self.subTest(disable_fence=disable_fence):
                m = self.machine().real_inputs()
                m.write(HID + 0x0E, b"\0"); m.write(HID + 0x13, b"\x01")
                m.source_front(0)
                self.assertEqual(m.read(APP + 0x18, 1), b"\0")
                self.assertEqual(m.read(APP + 0x28, 2), b"\x30\0")
                self.assertEqual(m.read(0x20003044, 2), b"\x30\0")
                self.assertEqual(m.read(QUEUE + 12, 6), bytes.fromhex("020103300000"))
                m.write(HID + 0x0E, b"\x01"); m.enter_hid()
                m.run(0x476C, 0x35D4)
                hid_context = m.emu.context_save()
                m.turn(0x400)
                self.assertEqual(m.checked_call("rc_enabled"), 1)
                self.assertEqual(m.read_state().handoff_mask & 3, 2)
                self.assertEqual(bytes(m.read_state().core.accepted), bytes(16))
                if disable_fence:
                    state = m.read_state(); state.handoff_mask = 0; m.write_state(state)
                m.source_front(0)  # Real native1DAC/1AF4/21DC on a held repeat.
                m.emu.context_restore(hid_context); m.run(0x35D4, 0x47AA)
                self.assertEqual(m.notifications, [(2, b"\x30\0\0")])
                m.assert_hid_return()
                m.checked_call("rc_hid_worker")
                powers = lambda: sum(report == 2 and data == b"\x30\0\0"
                                     for report, data in m.notifications)
                self.assertEqual(powers(), 2 if disable_fence else 1)
                if not disable_fence:
                    self.assertEqual(m.read_state().handoff_mask & 2, 2,
                        "Worker neutralization must not act as a physical release")
                    m.source_front(0); m.checked_call("rc_hid_worker")
                    self.assertEqual(powers(), 1)
                m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(m.read_state().handoff_mask & 2, 0)
                m.source_front(0); m.source_front(); m.checked_call("rc_hid_worker")
                self.assertEqual(powers(), 3 if disable_fence else 2)
                self.assertNotIn(0x1DAC, m.stubs); self.assertNotIn(0x1AF4, m.stubs)

    def test_complete_next_slot_is_private_before_publishing_index_including_wrap(self):
        for head in (0, 1, 2):
            with self.subTest(head=head):
                m = self.machine(); slot, data = m.arm(head)
                decoder = native.Cs(native.CS_ARCH_ARM, native.CS_MODE_THUMB | native.CS_MODE_MCLASS)
                start = m.address("rc_native_legacy_snapshot")
                publish = [i.address for i in decoder.disasm(m.image[start:start + 200], start)
                           if i.mnemonic == "strb" and i.op_str == "r0, [r6, #0x14]"]
                self.assertEqual(len(publish), 1)
                seen = []
                def before_publish(machine):
                    self.assertEqual(machine.depth, 1)
                    self.assertEqual(machine.read(HID + 0x14, 1), bytes([head]))
                    self.assertEqual(machine.read(HID_STACK - 48, 12), slot)
                    seen.append(1)
                m.observers[publish[0]] = before_publish
                m.run(0x476C, 0x4EF4)
                self.assertEqual(seen, [1])
                self.assertEqual(m.read(HID + 0x14, 2), bytes([(head + 1) % 3]) * 2)
                self.assertEqual(tuple(m.argument(i) for i in range(4)), (2, 1, 3, HID_STACK - 45))
                self.assertEqual(m.emu.reg_read(UC_ARM_REG_SP), HID_STACK - 48)
                self.assertEqual(m.depth, 0)
                m.run(0x4EF4, 0x47AA)
                self.assertEqual(m.notifications, [(2, data)])
                self.assertEqual([source for _, source, length in m.copies if length == 3],
                                 [HID_STACK - 45, HID_STACK - 45])
                m.assert_hid_return()

    def test_magic_claim_during_native_rpc_preserves_shadow_and_skips_legacy_postlude(self):
        for boundary in (0x35D4, 0x4668, 0x34B8):
            with self.subTest(boundary=hex(boundary)):
                m = self.machine(); slot, data = m.arm()
                m.run(0x476C, boundary)
                self.assertEqual(m.read(HID_STACK - 48, 12), slot)
                self.assertEqual(m.read(HID + 0x14, 2), b"\x01\x01")
                # Exercise the shim's raw-marker fence independently of C
                # admission, including a deliberately invalid state pointer.
                m.write(QUEUE, struct.pack("<II", 0x53465243, 3) + bytes(28))
                m.write(HID + 0x14, b"\0\x01")  # A stale postlude would repost.
                header = m.read(QUEUE, 36)
                def stale_legacy(machine):
                    self.fail("Claimed legacy indexes/post must not be revisited")
                m.stub(0x479E, stale_legacy); m.stub(0x4834, stale_legacy)
                m.run(boundary, 0x47AA)
                self.assertEqual(m.notifications, [(2, data)])
                self.assertEqual(m.read(HID + 3, 3), data)
                self.assertEqual(m.read(QUEUE, 36), header)
                self.assertEqual([source for _, source, length in m.copies if length == 3],
                                 [HID_STACK - 45, HID_STACK - 45])
                m.assert_hid_return()

    def test_nine_byte_payload_fits_shadow_and_corrupt_lengths_are_not_transmitted(self):
        for length in (9, 10, 255):
            with self.subTest(length=length):
                m = self.machine(); slot, data = m.arm(2, length, report=1)
                before = m.read(QUEUE, 36)
                m.run(0x476C, 0x47AA)
                self.assertEqual(m.read(HID + 0x14, 2), b"\0\0")
                self.assertEqual(m.notifications, [(1, data)] if length == 9 else [])
                self.assertEqual(m.read(QUEUE, 36), before)
                self.assertEqual(m.read(HID_STACK - 48, 12), slot)
                if length > 9:
                    self.assertEqual(m.parameter_updates, [])
                    self.assertEqual(m.notify_allocations, 0)
                m.assert_hid_return()

    def test_published_rear_release_while_uart_unready_leaves_hold_cache_stale(self):
        for count in (0, 1):
            with self.subTest(count=count):
                m = DispatchMachine(self.compiled, self, baseline=True)
                m.configure_rear(); m.rear(2)
                self.assertEqual(m.read(APP + 0x1B, 1), b"\x02")
                cache = m.read(0x20001789, 3)
                self.assertEqual(cache, b"\x04\0\0")
                m.write(UART + 9, b"\0")
                m.write(native.INPUT, b"\xff")
                m.checked_call(0x1A90, count, native.INPUT)
                m.checked_call(0x1878)
                # Count0 copies no mailbox payload, so1FDA's early unready
                # branch even retains the preceding scan in pendingAPP17.
                self.assertEqual(m.read(APP + 0x17, 1), b"\x02" if count == 0 else b"\xff")
                self.assertEqual(m.read(APP + 0x1B, 1), b"\x02")
                self.assertEqual(m.read(0x20001789, 3), cache,
                    "A cache-only admission fence cannot infer this physical release")


if __name__ == "__main__":
    unittest.main(verbosity=2)
