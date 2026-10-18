"""Execute the linked adapter, core and relevant factory code as Thumb.

The allocator, RTOS events, clock, GPIO, radio and peer/NV APIs are explicit
fixtures. These checks establish software contracts, not hardware qualification.
In particular the notification wrapper at 0x4f58, lookup at 0x4ec4 and UART
IRQ/worker/parser code run from the patched image rather than Python models.
"""
import ctypes
from pathlib import Path
import struct
import tempfile
import unittest

from test_adapter_initialization import InitMachine, native, ALLOC

APP, HID, UART, INPUT, STACK = native.APP, native.HID, native.UART, native.INPUT, native.STACK
TABLE, ATTRIBUTE, POINTER, CCC = 0x20003A00, 0x20003B00, 0x20003C00, 0x20003D00
MESSAGE = 0x20005000


class CoreView(ctypes.LittleEndianStructure):
    _fields_ = [("source", ctypes.c_uint8 * 128), ("tx", ctypes.c_uint8 * 256)] + [
        (name, ctypes.c_uint32) for name in ("peer", "token", "retry_started", "retry_due",
            "dropped_source", "dropped_tx", "expired", "invalid", "retries")] + [
        ("epoch", ctypes.c_uint16)] + [(name, ctypes.c_uint8) for name in (
            "source_head", "source_count", "tx_head", "tx_count", "connected", "cccd", "protocol",
            "repair_mask", "quarantine_mask", "release_mask", "admitted_mask")] + [
        ("admitted", ctypes.c_uint8 * 16), ("accepted", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint8) for name in ("flight_id", "flight_repair", "flight_len", "flight_pos")] + [
        ("flight_data", ctypes.c_uint8 * 8)] + [(name, ctypes.c_uint8) for name in (
            "retry_step", "retry_active", "wait_event")] + [
        ("parser", ctypes.c_uint8 * 6), ("parser_count", ctypes.c_uint8), ("source_barrier", ctypes.c_uint8)]


class StateView(ctypes.LittleEndianStructure):
    _fields_ = [("core", CoreView)] + [(name, ctypes.c_uint32) for name in (
        "tick_last", "milliseconds", "tick_remainder", "accounted_at", "connected_ms", "uart_ms", "idle_ms",
        "connection_changes", "last_front_index", "partial_reads")] + [
        ("minimum_free", ctypes.c_uint16), ("last_handle", ctypes.c_uint16)] + [
        (name, ctypes.c_uint8) for name in ("last_role", "last_uart", "identity_verified", "diag_page")] + [
        ("bond_address", ctypes.c_uint8 * 6), ("last_connected_address", ctypes.c_uint8 * 6),
        ("control_started", ctypes.c_uint32)] + [
        (name, ctypes.c_uint8) for name in ("control_pending", "control_fenced", "control_length", "control_value",
            "clock_initialized")] + [("dispatch_epoch",ctypes.c_uint16),("dispatch_active",ctypes.c_uint8),
            ("bond_valid",ctypes.c_uint8),("source_ticks",ctypes.c_uint32*16),("dispatch_expired",ctypes.c_uint8),
            ("pending_rear_tick",ctypes.c_uint32),("pending_rear_epoch",ctypes.c_uint16),
            ("pending_rear_index",ctypes.c_uint8)]


class RuntimeMachine(InitMachine):
    def __init__(self, compiled, case):
        super().__init__(compiled, case)
        # Unicorn 2.1.4's write hook changes flags in the factory memcpy's IT
        # loop (independently reproduced in the initialization suite). Keep
        # that real routine and verify the complete RAM diff at call boundaries
        # instead; the freestanding core/adapter suites retain write guards.
        self.emu.hook_del(self.write_guard)
        self.events, self.timers, self.notifications, self.attempts = [], [], [], []
        self.parameter_updates, self.advertisements, self.controls, self.disconnects = [], [], [], []
        self.fail_allocations, self.notify_status = 0, 0
        self.fail_at = set()
        self.notify_allocations, self.cccd = 0, 3
        self.uart_chunks, self.decoded = [], []
        self.write32(HID + 0x24, TABLE)
        self.emu.mem_write(HID + 0x12, b"\x03")
        self.emu.mem_write(HID + 0x0E, b"\x01")
        self.emu.mem_write(HID + 0x16, b"\x01")
        self.emu.mem_write(HID + 0x18, struct.pack("<H", 0x2345))
        for index, (report_id, protocol) in enumerate([(1, 1), (2, 1), (1, 0)]):
            attr, ptr, ccc = ATTRIBUTE + index * 16, POINTER + index * 4, CCC + index * 8
            self.emu.mem_write(TABLE + index * 12,
                struct.pack("<H2xIBBBB", 0x40 + index, attr, report_id, 1, protocol, 0))
            self.write32(attr + 12, ptr)
            self.write32(ptr, ccc)
        self.stubs.pop(0x4EC4)  # Execute the real protocol-aware factory lookup.
        self.stub(0x72AA, self.get_cccd)
        self.stub(0x4668, self.notification_allocate)
        self.stub(0x34B8, self.generic)
        self.stub(0x1330, lambda m: self.outside(m))  # Failed notification frees its native buffer.
        self.stub(0x60, self.post)
        self.stub(0xF6, self.timer)
        self.stub(0xF2, lambda m: self.outside(m))
        self.stub(0x4BC8, lambda m: self.outside(m))
        self.stub(0x35D4, self.parameters)
        self.stub(0x4BF8, self.advertise)
        self.stub(0x39E6, self.disconnect)
        self.stub(0x756A, self.uart_read)
        self.stub(0x6FBE, lambda m: self.outside(m, 0))
        self.stub(0x74DC, lambda m: self.outside(m))
        self.stub(0x30C, lambda m: self.outside(m))
        self.stub(0x5400, lambda m: self.outside(m))
        self.stub(0x707E, lambda m: self.outside(m))
        self.stub(0x1DAC, self.front_decoded)
        self.stub(0x1FDA, self.rear_decoded)
        self.write32(UART + 0x18, 0x1ABC | 1)
        self.write32(UART + 0x10, 0x20005F00)
        self.emu.mem_write(UART + 2, b"\xff")
        self.emu.mem_write(UART + 5, b"\x01")

    @staticmethod
    def allowed_ranges():
        return [(ALLOC, ALLOC + 640), (0x200027C8, 0x200027C8 + 36),
            (APP, APP + 0x1B0), (HID, HID + 0x180), (UART, UART + 0x100),
            (0x20003044, 0x20003046), (MESSAGE, MESSAGE + 64), (INPUT, INPUT + 512),
            (STACK - 0x1000, STACK + 32), (0x20000664, 0x20000664 + 21)]

    def check_write(self, emu, access, address, size, value, data):
        allowed = self.allowed_ranges()
        self.case.assertTrue(any(a <= address and address + size <= b for a, b in allowed),
                             f"Runtime write outside reviewed ranges: {address:#x}+{size}")
        self.writes.append((address, size))

    def checked_call(self, symbol, *arguments):
        before=bytes(self.emu.mem_read(0x20000000,0x8000))
        result=super().checked_call(symbol,*arguments)
        after=bytes(self.emu.mem_read(0x20000000,0x8000))
        allowed=self.allowed_ranges()
        for index,(old,new) in enumerate(zip(before,after)):
            if old!=new:
                at=0x20000000+index
                self.case.assertTrue(any(a<=at<b for a,b in allowed),f"Out-of-range RAM change {at:#x}")
        return result

    def read_state(self):
        return StateView.from_buffer_copy(bytes(self.emu.mem_read(ALLOC, ctypes.sizeof(StateView))))

    def write_state(self, state):
        self.emu.mem_write(ALLOC, bytes(state))

    def advance(self, milliseconds):
        self.tick = (self.tick + milliseconds * 100) & 0xFFFFFFFF

    def ready(self):
        self.checked_call("rc_app_init")
        self.case.assertEqual(self.allocations, [ctypes.sizeof(StateView)])
        self.case.assertEqual(ctypes.sizeof(CoreView), 488)
        self.checked_call("rc_hid_worker")
        self.case.assertEqual([(x[0], x[1]) for x in self.notifications], [(1, bytes(8)), (2, bytes(3))])
        self.notifications.clear(); self.attempts.clear(); self.timers.clear(); self.events.clear()
        return self

    def post(self, m):
        self.case.assertEqual(self.depth, 0)
        self.events.append((m.argument(0), m.argument(1)))
        m.ret(clobber=True)

    def timer(self, m):
        self.case.assertEqual(self.depth, 0)
        self.timers.append((m.argument(0), m.argument(1)))
        m.ret(clobber=True)

    def get_cccd(self, m):
        self.case.assertEqual(self.depth, 0)
        self.case.assertEqual(m.argument(0),struct.unpack("<H",m.emu.mem_read(HID+0x18,2))[0])
        index = (m.argument(1) - CCC) // 8
        self.case.assertIn(index, (0, 1, 2))
        m.ret(int(bool(self.cccd & (2 if index == 1 else 1))), clobber=True)

    def notification_allocate(self, m):
        self.case.assertEqual(self.depth, 0, "BLE allocation cannot occur inside the gate")
        self.case.assertEqual((m.argument(0),m.argument(1),m.argument(3)),
            (struct.unpack("<H",m.emu.mem_read(HID+0x18,2))[0],0x1B,0))
        self.notify_allocations += 1
        if self.notify_allocations in self.fail_at:
            self.fail_at.remove(self.notify_allocations);m.ret(0,clobber=True);return
        if self.fail_allocations:
            self.fail_allocations -= 1; m.ret(0, clobber=True)
        else:
            m.ret(MESSAGE, clobber=True)

    def generic(self, m):
        self.case.assertEqual(self.depth, 0, "native stack calls cannot occur inside the gate")
        if m.argument(2) == 0x419:
            return super().bond_get(m)
        if m.argument(2) == 0x409:
            length, ptr = m.argument(3), m.argument(4)
            self.controls.append((length, bytes(m.emu.mem_read(ptr, length)) if length else b""))
            m.ret(0, clobber=True); return
        self.case.assertEqual((m.argument(0), m.argument(1), m.argument(2), m.argument(4)),
                             (0x10,0x10010045,struct.unpack("<H",m.emu.mem_read(HID+0x18,2))[0],0))
        handle, length, ptr = struct.unpack("<HHI", m.emu.mem_read(m.argument(3), 8))
        report_id = 2 if handle == 0x41 else 1
        data = bytes(m.emu.mem_read(ptr, length))
        self.attempts.append((report_id, data, self.notify_status))
        if self.notify_status == 0:
            self.notifications.append((report_id, data))
        m.ret(self.notify_status, clobber=True)

    def parameters(self, m):
        self.case.assertEqual(self.depth, 0)
        self.parameter_updates.append((m.argument(0), m.argument(1),
                                      bytes(m.emu.mem_read(m.argument(2), m.argument(1)))))
        m.ret(0, clobber=True)

    def advertise(self, m):
        self.advertisements.append((m.argument(0), m.argument(1)))
        self.outside(m)

    def disconnect(self, m):
        self.disconnects.append(1); self.outside(m)

    def uart_read(self, m):
        self.case.assertEqual(self.depth, 0)
        self.case.assertEqual(m.argument(0), 0x20005F00)
        self.case.assertLessEqual(m.argument(2), 6)
        chunk = self.uart_chunks.pop(0) if self.uart_chunks else b""
        wanted = m.argument(2)
        if len(chunk) > wanted:
            self.uart_chunks.insert(0, chunk[wanted:]); chunk = chunk[:wanted]
        m.emu.mem_write(m.argument(1), chunk)
        m.ret(len(chunk), clobber=True)

    def front_decoded(self, m):
        self.case.assertEqual(self.depth, 0)
        count, special = m.argument(0), m.argument(2)
        self.decoded.append(("front", count, special,
            bytes(m.emu.mem_read(m.argument(1), 1 if special == 0xF1 else count))))
        m.ret(clobber=True)

    def rear_decoded(self, m):
        self.case.assertEqual(self.depth, 0)
        self.decoded.append(("rear", m.argument(0), 0,
            bytes(m.emu.mem_read(m.argument(1), m.argument(0)))))
        m.ret(clobber=True)


class AdapterRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-native-runtime-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled = native.compile_integration(cls.temporary.name)

    def machine(self):
        return RuntimeMachine(self.compiled, self).ready()

    def consumer(self, m, usage):
        return m.checked_call(0x21DC, usage)

    def keyboard(self, m, keys):
        m.emu.mem_write(INPUT, keys)
        return m.checked_call(0x2170, 0, INPUT)

    def test_both_report_paths_use_actual_notify_wrapper_and_full_keyboard_deduplication(self):
        m = self.machine()
        self.keyboard(m, b"\x04\0\0\0\0\0")
        self.keyboard(m, b"\x04\0\0\0\0\x05")
        self.consumer(m, 0x45); self.consumer(m, 0)
        self.keyboard(m, bytes(6))
        m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [(1,b"\0\0\x04\0\0\0\0\0"),
            (1,b"\0\0\x04\0\0\0\0\x05"),(2,b"\x45\0\0"),(2,bytes(3)),(1,bytes(8))])
        self.assertIn(0x4668, m.trace); self.assertIn(0x34B8, m.trace)
        self.assertEqual(m.read_state().core.release_mask, 0)

    def test_allocation_failure_retains_report_and_caches_until_native_retry_accepts(self):
        m = self.machine(); m.fail_allocations = 1
        m.emu.mem_write(HID + 0x13, b"\x01")
        self.consumer(m, 0x45)
        cache = bytes(m.emu.mem_read(HID, 12))
        m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [])
        self.assertEqual(bytes(m.emu.mem_read(HID, 12)), cache)
        self.assertEqual(bytes(m.emu.mem_read(0x20003044,2)), b"\0\0")
        self.assertEqual(m.parameter_updates, [(0x319,1,b"\x01")])
        self.assertEqual(m.read_state().core.tx_count, 1)
        self.assertEqual(m.timers[-1], (HID + 0x84,20))
        m.advance(19);m.checked_call("rc_timer_callback");m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [])
        m.advance(1);m.checked_call("rc_timer_callback");m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications, [(2,b"\x45\0\0")])
        self.assertEqual(bytes(m.emu.mem_read(0x20003044,2)), b"\x45\0")
        self.assertEqual(len(m.parameter_updates), 1)

    def test_notification_allocation_failure_at_each_of_sixteen_queue_positions(self):
        expected=[]
        for index in range(4):
            expected.extend([(1,bytes([0,0,4+index,0,0,0,0,0])),(1,bytes(8)),
                             (2,bytes([0x45+index,0,0])),(2,bytes(3))])
        for position in range(16):
            with self.subTest(position=position):
                m=self.machine()
                for index in range(4):
                    self.keyboard(m,bytes([4+index,0,0,0,0,0]));self.keyboard(m,bytes(6))
                    self.consumer(m,0x45+index);self.consumer(m,0)
                self.assertEqual(m.read_state().core.tx_count,16)
                m.fail_at.add(m.notify_allocations+position+1)
                m.checked_call("rc_hid_worker")
                self.assertEqual(m.notifications,expected[:position])
                m.advance(20);m.checked_call(0x50B8);m.checked_call("rc_hid_worker")
                self.assertEqual(m.notifications,expected)
                self.assertEqual(m.read_state().core.tx_count,0)
                self.assertEqual(m.read_state().core.release_mask,0)

    def test_unavailable_waits_for_useful_event_and_native_readiness_callback_wakes_once(self):
        m = self.machine();m.emu.mem_write(HID + 0x16,b"\0")
        self.consumer(m,0x45);m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().core.wait_event,2)
        for _ in range(3): m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications,[])
        self.assertEqual(m.timers,[])
        m.checked_call(0x50B8);m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications,[(2,b"\x45\0\0")])
        m.notify_status=0x17;self.consumer(m,0);m.checked_call("rc_hid_worker")
        attempts=len(m.attempts)
        for _ in range(4): m.checked_call("rc_timer_callback");m.checked_call("rc_hid_worker")
        self.assertEqual(len(m.attempts),attempts,"periodic readiness callbacks cannot restart unavailable TX")

    def test_retry_delays_budget_two_seconds_and_clock_millisecond_wrap(self):
        m=self.machine();s=m.read_state();s.milliseconds=0xFFFFFFF0;s.accounted_at=s.milliseconds;m.write_state(s)
        m.fail_allocations=100;self.consumer(m,0x45);m.checked_call("rc_hid_worker")
        self.assertEqual(m.timers[-1],(HID+0x84,20))
        for delay in [20,50,100,200]:
            m.advance(delay);m.checked_call("rc_timer_callback");m.checked_call("rc_hid_worker")
            if delay!=200:self.assertEqual(m.timers[-1][1],{20:50,50:100,100:200}[delay])
        m.advance(2000);m.checked_call("rc_timer_callback");m.checked_call("rc_hid_worker")
        allocations=m.notify_allocations
        for _ in range(4):m.checked_call("rc_hid_worker")
        self.assertEqual(m.notify_allocations,allocations)
        self.assertEqual(m.read_state().core.tx_count,0)
        self.assertGreater(m.read_state().core.expired,0)

    def test_mixed_saturation_protects_independent_release_mailboxes(self):
        m=self.machine()
        self.keyboard(m,b"\x04\0\0\0\0\0");self.consumer(m,0x45);m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().core.release_mask,3)
        for index in range(16):
            if index&1:self.consumer(m,0x46+index)
            else:self.keyboard(m,bytes([5+index,0,0,0,0,0]))
        self.assertEqual(m.read_state().core.tx_count,16)
        self.consumer(m,0);self.keyboard(m,bytes(6))
        self.assertEqual(m.read_state().core.repair_mask&2,2)
        self.consumer(m,0x60)
        m.checked_call("rc_hid_worker")
        self.assertEqual(dict(m.notifications),{1:bytes(8),2:bytes(3)})
        self.assertEqual([data for report,data in m.notifications[2:] if report==2],[bytes(3)])
        self.assertEqual(m.read_state().core.release_mask,0)
        self.assertEqual(m.read_state().core.tx_count,0)

    def test_cccd_disable_reenable_purges_old_taps_and_sends_neutral_first(self):
        m=self.machine();self.consumer(m,0x45)
        m.cccd=1;m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications,[])
        m.cccd=3;m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications,[(2,bytes(3))])
        self.assertEqual(m.read_state().core.tx_count,0)
        self.consumer(m,0x45);m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications[-1],(2,b"\x45\0\0"))

    def test_disconnect_pair_change_and_unknown_peer_never_replay_power(self):
        m=self.machine();self.consumer(m,0x30);m.checked_call("rc_hid_worker")
        self.consumer(m,0);self.consumer(m,0x30)
        m.emu.mem_write(HID+0xD,b"\x05");m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().core.tx_count,0)
        m.saved_peer=b"\x06\x05\x04\x03\x02\x01";m.connected_peer=m.saved_peer
        m.emu.mem_write(HID+0xD,b"\x06");m.checked_call("rc_hid_worker")
        self.assertEqual([d for i,d in m.notifications if i==2 and any(d)],[b"\x30\0\0"])
        self.consumer(m,0x45);m.connected_peer=b"\x10"*6;m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().identity_verified,0)
        self.assertEqual(m.read_state().core.tx_count,0)

    def test_peer_change_between_source_pop_and_report_admission_drops_old_event(self):
        m=self.machine();old_epoch=m.read_state().core.epoch
        m.emu.mem_write(INPUT,b"\x24");m.checked_call(0x1ABC,1,INPUT,0)
        def preempted_front(x):
            # Explicit interleaving seam: a HID connection callback preempts
            # APP after pop, before this native handler submits its HID usage.
            x.saved_peer=b"\x11\x12\x13\x14\x15\x16";x.connected_peer=x.saved_peer
            x.emu.reg_write(native.UC_ARM_REG_R0,0x45)
            x.emu.reg_write(native.UC_ARM_REG_PC,x.symbols["rc_consumer"]|1)
        m.stub(0x1DAC,preempted_front)
        m.checked_call(0x1878);m.checked_call("rc_hid_worker")
        self.assertNotEqual(m.read_state().core.epoch,old_epoch)
        self.assertFalse(any(any(data) for _,data in m.notifications))
        self.assertEqual(m.read_state().core.tx_count,0)

    def test_new_connection_handle_without_intermediate_callback_still_purges_old_command(self):
        m=self.machine();old_epoch=m.read_state().core.epoch
        self.consumer(m,0x30)
        m.emu.mem_write(HID+0x18,struct.pack("<H",0x2346))
        m.checked_call("rc_hid_worker")
        self.assertNotEqual(m.read_state().core.epoch,old_epoch)
        self.assertEqual(m.notifications,[(1,bytes(8)),(2,bytes(3))])
        self.assertEqual(m.read_state().core.tx_count,0)

    def test_source_queue_press_expires_before_dispatch_but_release_and_uart_ack_survive(self):
        m=self.machine()
        m.emu.mem_write(INPUT,b"\x24");m.checked_call(0x1ABC,1,INPUT,0)
        m.emu.mem_write(INPUT,b"\x04");m.checked_call(0x1A90,1,INPUT)
        m.advance(2000);m.checked_call(0x1878)
        self.assertEqual(m.decoded,[])
        self.assertGreaterEqual(m.read_state().core.expired,2)
        m.checked_call(0x1A90,0,INPUT);m.checked_call(0x1ABC,0,INPUT,0)
        m.advance(2000);m.checked_call(0x1878)
        self.assertEqual(m.decoded,[("rear",0,0,b""),("front",0,0,b"")])
        m=self.machine();m.uart_chunks=[b"\xfe\x01\x01\x24\xff\xff"]
        self.irq_then_worker(m);m.advance(2000);m.checked_call(0x1878)
        self.assertFalse(any(count for _,count,_,_ in m.decoded))
        self.assertTrue(m.timers,"expired raw UART still follows its native ACK/session timing")

    def test_tick_counter_wrap_retains_sub_millisecond_remainder(self):
        m=self.machine();s=m.read_state();s.tick_last=0xFFFFFFCE;s.tick_remainder=99;m.write_state(s)
        start=s.milliseconds;m.tick=49;m.checked_call("rc_hid_worker")
        s=m.read_state();self.assertEqual(s.milliseconds-start,1);self.assertEqual(s.tick_remainder,98)

    def irq_then_worker(self,m):
        m.checked_call(0x56E0);m.checked_call(0x5648)

    def test_uart_every_split_survives_actual_irq_worker_and_preserves_orientation_key_order(self):
        frame=b"\xfe\x01\x01\x24\xff\xff"
        for split in range(1,6):
            with self.subTest(split=split):
                m=self.machine();m.uart_chunks=[frame[:split]]
                self.irq_then_worker(m)
                self.assertEqual(m.read_state().core.parser_count,split)
                self.assertEqual(bytes(m.emu.mem_read(UART+7,1)),b"\0")
                m.uart_chunks=[frame[split:]]
                self.irq_then_worker(m)
                m.emu.mem_write(INPUT,b"\x04");m.checked_call(0x1A90,1,INPUT)
                m.checked_call(0x1878)
                self.assertEqual(m.decoded,[("front",0,0xF1,b"\x01"),
                    ("front",1,0,b"\x24"),("rear",1,0,b"\x04")])

    def test_full_bad_uart_frame_rearms_next_irq_and_timeout_discards_fragments(self):
        for bad in [bytes(6),b"\xfe\0\x03\0\0\0",b"\xfe\0\x01\x2d\0\0"]:
            with self.subTest(bad=bad.hex()):
                m=self.machine();m.uart_chunks=[bad];self.irq_then_worker(m)
                self.assertEqual(bytes(m.emu.mem_read(UART+7,1)),b"\0")
                m.uart_chunks=[b"\xfe\0\x01\x24\xff\xff"]
                self.irq_then_worker(m);m.checked_call(0x1878)
                self.assertEqual(m.decoded,[("front",1,0,b"\x24")])
        m=self.machine();m.uart_chunks=[b"\xfe\x01"]
        self.irq_then_worker(m);self.assertEqual(m.read_state().core.parser_count,2)
        m.emu.mem_write(UART+4,b"\x04");m.checked_call(0x5648)
        self.assertEqual(m.read_state().core.parser_count,0)
        m.uart_chunks=[b"\xfe\0\x01\x24\xff\xff"]
        self.irq_then_worker(m);m.checked_call(0x1878)
        self.assertEqual(m.decoded,[("front",1,0,b"\x24")])

    def test_normal_control_repairs_both_reports_and_forced_control_precedes_reset(self):
        m=self.machine();self.keyboard(m,b"\x04\0\0\0\0\0");self.consumer(m,0x45)
        m.checked_call("rc_hid_worker")
        self.consumer(m,0x46);self.keyboard(m,b"\x05\0\0\0\0\0")
        m.checked_call(0x2248,0)
        self.assertEqual(m.controls,[])
        self.consumer(m,0x50);m.checked_call("rc_hid_worker")
        self.assertEqual(m.notifications[-2:],[(1,bytes(8)),(2,bytes(3))])
        self.assertEqual(m.controls,[(0,b"")]);self.assertEqual(m.disconnects,[1])
        self.assertEqual(m.read_state().core.tx_count,0)
        m=self.machine()
        self.consumer(m,0x45);m.checked_call(0x2248,1)
        self.assertEqual(m.controls,[(1,b"\x01")])
        self.assertEqual(m.notifications,[]);self.assertEqual(m.read_state().core.tx_count,0)

    def test_control_unavailable_release_deadline_does_not_block_pairing_forever(self):
        m=self.machine();self.consumer(m,0x45);m.checked_call("rc_hid_worker")
        m.emu.mem_write(HID+0x16,b"\0")  # Native idle can clear readiness after a previously accepted report.
        m.notify_status=0x17;m.checked_call(0x48F4,0,0,0);m.checked_call("rc_hid_worker")
        self.assertEqual(m.controls,[])
        self.assertEqual(m.timers[-1],(HID+0x84,2000))
        m.advance(2000);m.checked_call(0x50B8);m.checked_call("rc_hid_worker")
        self.assertEqual(m.controls,[(0,b"")]);self.assertEqual(m.disconnects,[1])

    def test_heap_and_uart_activity_samples_track_transitions_without_power_claim(self):
        m=self.machine();m.free_after=900;m.checked_call("rc_hid_worker")
        self.assertEqual(m.read_state().minimum_free,900)
        m.advance(100);m.uart_chunks=[b"\xfe\0\x01\x24\xff\xff"]
        self.irq_then_worker(m);m.checked_call(0x1878)
        m.advance(80);m.emu.mem_write(UART+4,b"\x04");m.checked_call(0x5648)
        before=m.read_state();m.advance(30000);m.checked_call("rc_hid_worker");after=m.read_state()
        self.assertEqual(after.uart_ms,before.uart_ms)
        self.assertEqual(after.idle_ms-before.idle_ms,30000)

    def test_usage_variant_keeps_input_transport_without_diagnostic_heap_sampling(self):
        with tempfile.TemporaryDirectory(prefix="sf463-usage-runtime-") as directory:
            compiled=native.compile_integration(directory,"usage")
            m=RuntimeMachine(compiled,self).ready()
            queries=len(m.heap_queries)
            self.keyboard(m,b"\x04\0\0\0\0\0");self.keyboard(m,bytes(6))
            self.consumer(m,0x45);self.consumer(m,0)
            m.advance(100);m.checked_call("rc_hid_worker")
            self.assertEqual(m.notifications,[(1,b"\0\0\x04\0\0\0\0\0"),
                (1,bytes(8)),(2,b"\x45\0\0"),(2,bytes(3))])
            self.assertEqual(len(m.heap_queries),queries,"usage removes periodic diagnostic heap queries")
            self.assertEqual(m.read_state().uart_ms,0)
            self.assertEqual(m.read_state().connected_ms,0)

    def test_diagnostic_exposes_last_valid_front_scan_index_without_release_overwrite(self):
        m=self.machine();m.configure_attribute()
        m.emu.mem_write(INPUT,b"\x1b");m.checked_call(0x1ABC,1,INPUT,0)
        m.emu.mem_write(INPUT,b"\xff");m.checked_call(0x1ABC,1,INPUT,0)
        m.checked_call(0x1878)
        pages=[m.read_info(0,20)[2] for _ in range(3)]
        raw=bytes.fromhex(pages[2].decode("ascii"))
        self.assertEqual(raw[0],2);self.assertEqual(raw[6],27)
        self.assertEqual(raw[9]&0xC0,0xC0,"verified peer and known physical scan index")
        self.assertEqual(raw[9]&31,m.read_state().core.tx_count)


if __name__ == "__main__":
    unittest.main()
