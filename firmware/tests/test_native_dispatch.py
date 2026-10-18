"""Real front decoder/dispatcher exercised through compiled adapter and core.

The pinned 06.07 is the comparison image. 0x1dac and 0x1af4 are NEVER stubbed.
Unmodified clock, LED, advertising and UART-control services are explicit API
seams, not physical devices. Physical color-button labels remain unverified.
"""
import struct
import tempfile
import unittest

from test_adapter_runtime import RuntimeMachine, native, APP, HID, UART, INPUT
from unicorn.arm_const import (UC_ARM_REG_SP,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7)


# Independent expected usages for the pinned 45-entry front map. These are
# usage/index expectations, not claims about unobserved physical button labels.
USAGES = (0x30,0x224,0xB0,0x40,0x221,0xEA,0x72,0x9D,0x191,
          0xB4,0xB1,0xB3,0x42,0x21,0x22,0x23,0x222,0xB7,
          0x6A,0xB2,0x41,0x24,0x25,0x26,0x44,0x69,0x6C,
          0x6C,0x63,0x27,0x28,0x29,0x43,0xE9,0x70,0x9C,
          0x45,0x90,0x20,0x8D,0x223,0xE2,0x1A7,0x89,0xF1)


class DispatchMachine(RuntimeMachine):
    def _instruction(self,emu,address,size,data):
        sp=emu.reg_read(UC_ARM_REG_SP)
        if not hasattr(self,"minimum_sp") or sp<self.minimum_sp:
            self.minimum_sp=sp
            self.minimum_sp_at=address
        if not hasattr(self,"api_stack_depths"):
            self.api_stack_depths={}
        if address in (0x2D54,0x26EE,0x34B8,0x3874,0x72AA,0x4668,0x35D4):
            self.api_stack_depths[address]=max(self.api_stack_depths.get(address,0),native.STACK-sp)
        return super()._instruction(emu,address,size,data)

    @staticmethod
    def allowed_ranges():
        # Published native keyboard serializer's three-byte dedupe cache,
        # resolved from its literal at0x2b08. The adapter uses its full cache.
        return RuntimeMachine.allowed_ranges()+[(0x20001789,0x2000178C)]

    def __init__(self,compiled,case,baseline=False):
        super().__init__(compiled,case)
        self.native_services=[]
        self.stubs.pop(0x1DAC)
        self.stubs.pop(0x1FDA)
        # Advertising and peripheral services retain their native call contract.
        # The front decoding, dispatch state machine and report path stay real.
        for address,count in ((0x2874,1),(0x2812,1),(0x270C,0),
                              (0x53DA,3),(0x5A1A,3),(0x598C,0)):
            self.stub(address,lambda m,a=address,n=count:self.service(m,a,n))
        self.stub(0x280C,lambda m:self.outside(m,0))
        self.ready()
        self.baseline=baseline
        if baseline:
            # Initialize the same external API fixture, then execute actual
            # published 06.07 instructions, including its native serializers.
            self.emu.mem_write(0,native.BASELINE)
        self.write(APP+0x0F,b"\x06")
        self.write(APP+0x12,b"\x05")
        self.write(APP+0x17,b"\xff")  # Native pending scan slot starts idle in this fixture.
        self.write(APP+0x18,b"\xff")
        self.write(APP+0x28,b"\0\0")
        self.native_services.clear()

    def service(self,m,address,count):
        self.case.assertEqual(self.depth,0)
        self.native_services.append((address,tuple(m.argument(i) for i in range(count))))
        m.ret(0,clobber=True)

    def front(self,index=None,*,combo=None,special=0):
        if combo is not None:
            payload=bytes(combo); count=len(payload)
        elif index is None:
            payload=b"\0\0"; count=0
        else:
            payload=bytes([index]); count=1
        self.write(INPUT,payload+b"\0"*6)
        # Actual native source decoder; it calls actual 0x1af4.
        return self.checked_call(0x1DAC,count,INPUT,special)

    def flush(self):
        if not self.baseline:
            self.checked_call("rc_hid_worker")

    def usages(self):
        return [int.from_bytes(data[:2],"little")
                for report,data in self.notifications if report==2]

    def configure_rear(self):
        # Exact initialized primary/alternate map pointers from the pinned
        # image's bounded IAR initialization, not synthetic keyboard maps.
        self.write32(APP+0x34,0x14860)
        self.write32(APP+0x38,0x148C0)
        self.write(UART+6,b"\x01")
        self.write(UART+9,b"\x01")
        self.write(APP+0x17,b"\xff")

    def rear(self,index=None):
        self.write(INPUT,bytes([index or 0]))
        self.checked_call(0x1A90,0 if index is None else 1,INPUT)
        self.checked_call(0x1878)
        self.flush()


class NativeDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix="sf463-real-dispatch-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.compiled=native.compile_integration(cls.temporary.name)

    def machine(self,baseline=False):
        return DispatchMachine(self.compiled,self,baseline)

    def test_every_front_index_and_release_execute_real_decoder_and_report_pipeline(self):
        for index,usage in enumerate(USAGES):
            with self.subTest(index=index,usage=hex(usage)):
                old,new=self.machine(True),self.machine()
                for m in (old,new):
                    self.assertNotIn(0x1DAC,m.stubs)
                    self.assertNotIn(0x1AF4,m.stubs)
                    m.front(index); m.front(255); m.flush()
                    self.assertEqual(m.read(APP+0x18,1),b"\xff")
                # F1 is a native hold-only pairing action, never a short tap.
                expected=[] if index==44 else [usage]
                self.assertEqual([x for x in old.usages() if x],expected)
                self.assertEqual([x for x in new.usages() if x],expected)
                if expected:
                    self.assertEqual(old.usages(),[usage,0])
                    self.assertEqual(new.usages(),[usage,0])
                self.assertEqual(new.native_services,old.native_services)

    def test_native_held_arrow_deduplicates_reports_and_releases_once(self):
        old,new=self.machine(True),self.machine()
        for m in (old,new):
            m.front(36)
            for _ in range(4):
                m.advance(50); m.front(36)
            self.assertEqual(struct.unpack("<H",m.read(APP+0x22,2))[0],4)
            m.flush(); m.front(); m.flush()
            self.assertEqual(m.usages(),[0x45,0])
        self.assertEqual(new.native_services,old.native_services)

    def test_native_hold_watchdog_boundary_requests_uart_close_only_above_555(self):
        for baseline in (True,False):
            with self.subTest(baseline=baseline):
                m=self.machine(baseline)
                m.front(36)
                m.write(APP+0x22,struct.pack("<H",0x22A))
                m.front(36)
                self.assertEqual(m.read(UART+0x0C,1),b"\0")
                m.front(36)
                self.assertEqual(m.read(UART+0x0C,1),b"\x01")
                m.front(); m.flush()
                self.assertEqual(m.usages(),[0x45,0])

    def test_native_pair_combo_hold_preserves_threshold_and_erase_arguments(self):
        old,new=self.machine(True),self.machine()
        for m in (old,new):
            m.front(combo=b"\x26\x29")
            for _ in range(24): m.front(combo=b"\x26\x29")
            self.assertEqual(m.controls,[])
            self.assertEqual(m.read(APP+0x0B,1),b"\0")
            m.front(combo=b"\x26\x29")
            self.assertEqual(m.read(APP+0x0B,1),b"\x01")
            m.flush()
            self.assertEqual(m.controls,[(0,b"")])
            self.assertEqual(len(m.disconnects),1)
            self.assertIn((0x5A1A,(0,3,2)),m.native_services)
            self.assertNotIn(0xF1,m.usages())

    def test_native_0x63_hold_preserves_erase_and_advertising_thresholds(self):
        old,new=self.machine(True),self.machine()
        for m in (old,new):
            m.front(28); m.flush()
            self.assertEqual(m.usages(),[0x63])
            m.write(APP+0x22,struct.pack("<H",13)); m.front(28)
            self.assertEqual(m.controls,[])
            m.front(28); m.flush()  # Native repeat counter reaches 15.
            self.assertEqual(m.controls,[(0,b"")])
            self.assertEqual(m.usages(),[0x63,0])
            self.assertNotIn((0x270C,()),m.native_services)
            m.write(APP+0x22,struct.pack("<H",18)); m.front(28)
            self.assertNotIn((0x270C,()),m.native_services)
            m.front(28)  # Native repeat counter reaches 20.
            self.assertIn((0x270C,()),m.native_services)
            self.assertEqual(m.read(APP+0x0B,1),b"\0")
            m.front(255)
            self.assertIn((0x53DA,(1,0,0xB7)),m.native_services)

    def test_invalid_front_source_is_fenced_before_real_decoder_and_valid_release_survives(self):
        m=self.machine()
        for index in (45,254):
            with self.subTest(index=index):
                m.write(INPUT,bytes([index]))
                m.checked_call(0x1ABC,1,INPUT,0)
                m.checked_call(0x1878)
                m.flush()
                self.assertEqual(m.notifications,[])
                self.assertEqual(m.read(APP+0x18,1),b"\xff")
        m.write(INPUT,b"\x24")
        m.checked_call(0x1ABC,1,INPUT,0)
        m.write(INPUT,b"\xff")
        m.checked_call(0x1ABC,1,INPUT,0)
        m.checked_call(0x1878); m.flush()
        self.assertEqual(m.usages(),[0x45,0])

    def test_native_voice_pending_and_ready_paths_match_published_state_machine(self):
        old,new=self.machine(True),self.machine()
        for m in (old,new):
            m.write(APP+0x0F,b"\x02")
            m.write(APP+0x12,b"\x03")
            m.front(4)
            self.assertEqual(m.read(APP+0x11,1),b"\x01")
            self.assertEqual(struct.unpack("<H",m.read(APP+0x20,2))[0]&0x400,0x400)
            m.front(); m.flush()
            self.assertNotIn(0x221,m.usages())
            m.write(APP+0x0F,b"\x06")
            m.write(APP+0x12,b"\x05")
            m.notifications.clear()
            m.front(4)
            self.assertEqual(m.read(APP+0x11,1),b"\x03")
            m.front(); m.flush()
            self.assertEqual(m.usages(),[0x221,0])
        self.assertEqual(new.native_services,old.native_services)

    def test_native_orientation_chords_keep_uart_and_keyboard_side_effects(self):
        for face,expected in ((0,b"\0\0\x6c\0\0\0\0\0"),
                              (1,b"\0\0\xe1\x6c\0\0\0\0")):
            with self.subTest(face=face):
                old,new=self.machine(True),self.machine()
                for m in (old,new):
                    m.front(face,special=0xF1); m.flush()
                    self.assertEqual(m.notifications,[(1,expected),(1,bytes(8))])
                self.assertEqual(new.native_services,old.native_services)

    def test_real_front_gate_retains_reconnect_tap_while_published_image_drops_it(self):
        old,new=self.machine(True),self.machine()
        for m in (old,new):
            m.write(APP+0x0F,b"\x02")
            m.write(APP+0x12,b"\x03")
            m.write(HID+0x0D,b"\x02")
            m.front(36); m.front()
            self.assertEqual(m.notifications,[])
            m.write(HID+0x0D,b"\x06")
            m.write(APP+0x0F,b"\x06")
            m.write(APP+0x12,b"\x05")
            m.flush()
        self.assertEqual(old.usages(),[])
        self.assertEqual([x for x in new.usages() if x],[0x45])
        self.assertEqual(new.usages()[-2:],[0x45,0])

    def test_rear_native_scan_indices_reach_real_keyboard_serializer(self):
        for index,usage in ((1,0x1D),(2,4),(3,0x14),(4,0x2C),(44,0x28),(47,0x2A)):
            with self.subTest(index=index,usage=usage):
                old,new=self.machine(True),self.machine()
                for m in (old,new):
                    self.assertNotIn(0x1FDA,m.stubs)
                    m.configure_rear()
                    m.rear(index); m.rear()
                    expected=bytes([0,0,usage,0,0,0,0,0])
                    self.assertEqual(m.notifications,[(1,expected),(1,bytes(8))])
                    self.assertEqual(m.read(APP+0x1B,1),b"\xff")
                self.assertEqual(new.native_services,old.native_services)

    def test_rear_native_letter_shift_release_sequence_matches_0607_exactly(self):
        old,new=self.machine(True),self.machine()
        histories=[]
        for m in (old,new):
            m.configure_rear()
            modes=[]
            for index in (2,None,0,None,2,None,4,None):
                m.rear(index)
                modes.append(m.read(APP+0x15,1)[0])
            self.assertEqual(modes,[0,0,0,1,1,0,0,0])
            expected=[bytes([0,0,4,0,0,0,0,0]),bytes(8),
                      bytes([0,0,0x6D,0,0,0,0,0]),bytes(8),
                      bytes([0,0,0xE1,4,0,0,0,0]),bytes(8),
                      bytes([0,0,0xE6,0x6D,0,0,0,0]),bytes(8),
                      bytes([0,0,0x2C,0,0,0,0,0]),bytes(8)]
            self.assertEqual(m.notifications,[(1,report) for report in expected])
            histories.append(m.native_services)
        self.assertEqual(histories[0],histories[1])

    def test_rear_pending_scan_code_replays_once_after_native_uart_readiness(self):
        for baseline in (True,False):
            with self.subTest(baseline=baseline):
                m=self.machine(baseline)
                m.configure_rear(); m.write(UART+9,b"\0")
                m.rear(2)
                self.assertEqual(m.notifications,[])
                self.assertEqual(m.read(APP+0x17,1),b"\x02")
                m.advance(1999)
                m.write(UART+9,b"\x01")
                # Native pending-rear timer is bit7 (LSLS #24), not bit8.
                m.write(APP+0x20,struct.pack("<H",0x80))
                m.checked_call(0x1878); m.flush()
                self.assertEqual(m.notifications,
                    [(1,bytes([0,0,4,0,0,0,0,0])),(1,bytes(8))])
                self.assertEqual(m.read(APP+0x17,1),b"\xff")
                m.checked_call(0x1878); m.flush()
                self.assertEqual(len(m.notifications),2)

    def test_rear_pending_scan_code_expires_from_original_source_timestamp(self):
        for source_wait in (0,1999):
            with self.subTest(source_wait=source_wait):
                m=self.machine()
                m.configure_rear(); m.write(UART+9,b"\0")
                m.write(INPUT,b"\x02"); m.checked_call(0x1A90,1,INPUT)
                m.advance(source_wait); m.checked_call(0x1878); m.flush()
                self.assertEqual(m.read(APP+0x17,1),b"\x02")
                self.assertEqual(m.notifications,[])
                m.advance(2000-source_wait)
                m.write(UART+9,b"\x01")
                m.write(APP+0x20,struct.pack("<H",0x80))
                m.checked_call(0x1878); m.flush()
                self.assertEqual(m.read(APP+0x17,1),b"\xff")
                self.assertFalse(any(any(data) for _,data in m.notifications),
                    "A native pending rear key must not regain a fresh TTL")
                self.assertFalse(m.read_state().core.release_mask & 1)

    def test_rear_pending_scan_code_never_crosses_connection_epoch(self):
        for transition in ("disconnect","peer","unobserved_peer"):
            with self.subTest(transition=transition):
                m=self.machine()
                m.configure_rear(); m.write(UART+9,b"\0"); m.rear(2)
                self.assertEqual(m.read(APP+0x17,1),b"\x02")
                epoch=m.read_state().core.epoch
                if transition=="disconnect":
                    m.write(HID+0xD,b"\x05"); m.flush()
                    m.write(HID+0xD,b"\x06"); m.flush()
                else:
                    m.saved_peer=b"\x11\x12\x13\x14\x15\x16"
                    m.connected_peer=m.saved_peer
                    if transition=="peer": m.flush()
                if transition!="unobserved_peer":
                    self.assertNotEqual(m.read_state().core.epoch,epoch)
                m.notifications.clear()
                m.write(UART+9,b"\x01")
                m.write(APP+0x20,struct.pack("<H",0x80))
                m.checked_call(0x1878); m.flush()
                self.assertNotEqual(m.read_state().core.epoch,epoch)
                self.assertEqual(m.read(APP+0x17,1),b"\xff")
                self.assertFalse(any(any(data) for _,data in m.notifications),
                    "A rear key retained outside Core must not cross a session fence")

    def test_rear_release_cancels_native_pending_scan_code_while_uart_is_unready(self):
        m=self.machine()
        m.configure_rear(); m.write(UART+9,b"\0"); m.rear(2)
        self.assertEqual(m.read(APP+0x17,1),b"\x02")
        m.rear()
        self.assertEqual(m.read(APP+0x17,1),b"\xff")
        m.write(UART+9,b"\x01")
        m.write(APP+0x20,struct.pack("<H",0x80))
        m.checked_call(0x1878); m.flush()
        self.assertFalse(any(any(data) for _,data in m.notifications))
        self.assertFalse(m.read_state().core.release_mask & 1)

    def test_untracked_native_pending_scan_code_is_cleared_without_replay(self):
        m=self.machine(); m.configure_rear()
        m.write(APP+0x17,b"\x02")
        m.write(APP+0x20,struct.pack("<H",0x80))
        m.checked_call(0x1878); m.flush()
        self.assertEqual(m.read(APP+0x17,1),b"\xff")
        self.assertFalse(any(any(data) for _,data in m.notifications))

    def test_native_task_stack_sizes_and_hid_inline_prefix_are_explicit(self):
        m=native.NativeMachine(self.compiled)
        constructions=[]
        def initialize_params(machine):
            machine.write(machine.argument(0),bytes(0x3C)); machine.ret(0,clobber=True)
        def construct(machine):
            params=machine.argument(2)
            constructions.append((machine.argument(0),machine.argument(1),
                machine.read32(params+0x1C),machine.read32(params+0x20),machine.read32(params+0x18)))
            machine.ret(0,clobber=True)
        m.stub(0x1338,initialize_params); m.stub(0x1340,construct)
        m.call(0x13AE); m.call(0x4670)
        self.assertEqual(constructions,[(0x200022A8,0x1735,0x200022F8,750,1),
                                       (0x200025E8,0x46A5,0x20002638,400,2)])
        m=self.machine()
        m.front(36)  # Real native decoder queued a real report for the worker.
        native_generic=m.stubs[0x34B8]
        def reject_bond_count(machine):
            self.fail("HID worker must not perform an NV bond-count query")
        def notification_only(machine):
            self.assertNotEqual(machine.argument(2),0x419,
                "HID worker must not query stored bond records")
            native_generic(machine)
        m.stub(0x26EE,reject_bond_count)
        m.stub(0x34B8,notification_only)
        m.seed()
        m.emu.reg_write(UC_ARM_REG_R5,4)
        m.emu.reg_write(UC_ARM_REG_R6,HID)
        m.emu.reg_write(UC_ARM_REG_R7,0x200027C8)
        # Include the permanent frame pushed by the native HID task at46A4.
        m.emu.reg_write(UC_ARM_REG_SP,native.STACK-32)
        m.minimum_sp=native.STACK
        m.api_stack_depths={}
        m.run(0x476C,0x47AA)
        prefix=native.STACK-m.minimum_sp
        self.assertLessEqual(prefix,400,
            "Compiled prefix alone exceeds native HID stack; API stacks remain unqualified")
        self.assertEqual(m.usages(),[0x45])


if __name__=="__main__":
    unittest.main(verbosity=2)
