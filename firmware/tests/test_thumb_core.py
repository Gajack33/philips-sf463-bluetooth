"""Execute the actual freestanding C core as Cortex-M3 Thumb instructions.

This qualifies only the portable core and its ARM ABI. It does not emulate the
native adapter, ROM, BLE, UART electrical interface, interrupts, or TV hardware.
No installed compiler is silently substituted when SF463_COMPILER is supplied.

Unicorn 2.1.4 fails to leave Clang 18's repair loop after its conditional STRB
when a MEM_WRITE hook is active; adding a CODE hook does not fix it. Check the
entire mapped RAM before/after each call instead, retaining ABI and sentinels.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
    UC_PROT_READ, UC_PROT_EXEC, UC_ERR_WRITE_PROT)
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sf463_thumb_builder", ROOT / "firmware/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
EXPORTS = ["sf_core_init", "sf_core_size", "sf_source_push", "sf_source_pop",
           "sf_uart_feed", "sf_front_index_valid", "sf_link", "sf_cccd",
           "sf_protocol", "sf_submit", "sf_tx_peek", "sf_tx_complete", "sf_wake", "sf_repair"]
STATE, INPUT, OUTPUT = 0x20000100, 0x20001000, 0x20001100
STACK, RETURN = 0x20007F00, 0x30000000
SAVED = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
         UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
ARGUMENTS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
ZERO = bytes(8)


def compile_core(directory):
    command = build.compiler_command(os.environ.get("SF463_COMPILER"))
    zig = len(command) == 2
    flags = (["-target", "thumb-freestanding-eabi"] if zig
             else ["--target=arm-none-eabi", "-fuse-ld=lld"])
    flags += ["-mcpu=" + ("cortex_m3" if zig else "cortex-m3"),
              "-mthumb", "-mfloat-abi=soft", "-Oz", "-std=c11", "-ffreestanding",
              "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
              "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections",
              "-Wall", "-Wextra", "-Werror", "-nostdlib", "-g" if zig else "-g0",
              "-Wl,--gc-sections", "-Wl,--build-id=none", f"-Wl,-T,{ROOT / 'firmware/linker.ld'}"]
    flags += [f"-Wl,-u,{symbol}" for symbol in EXPORTS]
    destination = Path(directory) / "core-thumb.elf"
    invocation = command + flags + [str(ROOT / "firmware/core/sf_core.c"), "-o", str(destination)]
    try:
        subprocess.run(invocation, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise AssertionError("Thumb core compilation failed:\n" + error.stderr) from error
    payload, symbols = build.elf_payload(destination.read_bytes())
    missing = [name for name in EXPORTS if name not in symbols]
    if missing:
        raise AssertionError(f"Missing ARM exports: {missing}")
    return payload, symbols


class ThumbCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sf463-thumb-core-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.payload, cls.symbols = compile_core(cls.temporary.name)
        cls.source_sha256 = hashlib.sha256((ROOT / "firmware/core/sf_core.c").read_bytes()).hexdigest()

    def setUp(self):
        self.emu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.emu.mem_map(0, 0x20000)
        self.emu.mem_write(build.PATCH_START, self.payload)
        self.emu.mem_map(0x20000000, 0x10000)
        self.emu.mem_map(RETURN, 0x1000)
        self.emu.mem_protect(0, 0x20000, UC_PROT_READ | UC_PROT_EXEC)
        self.emu.mem_protect(RETURN, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
        self.emu.mem_write(STATE - 16, b"\xa5" * 16)
        self.emu.mem_write(STATE + 640, b"\x5a" * 16)
        self.call("sf_core_init", STATE, 0)

    def checked_ram(self, before):
        after = bytes(self.emu.mem_read(0x20000000, 0x10000))
        permitted = [(STATE, STATE + 640), (INPUT, OUTPUT + 0x100),
                     (STACK - 0x1000, STACK + 0x100)]
        for index, (old, new) in enumerate(zip(before, after)):
            if old != new:
                address = 0x20000000 + index
                self.assertTrue(any(start <= address < end for start, end in permitted),
                    f"Core wrote outside reviewed state/arguments/stack: {address:#x}")

    def call(self, name, *arguments):
        self.emu.reg_write(UC_ARM_REG_SP, STACK)
        self.emu.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for index, register in enumerate(ARGUMENTS):
            self.emu.reg_write(register, arguments[index] & 0xFFFFFFFF if index < len(arguments) else 0)
        for index, value in enumerate(arguments[4:]):
            self.emu.mem_write(STACK + index * 4, struct.pack("<I", value & 0xFFFFFFFF))
        expected_saved = [0x41410000 + index * 0x101 for index in range(len(SAVED))]
        for register, value in zip(SAVED, expected_saved):
            self.emu.reg_write(register, value)
        before = bytes(self.emu.mem_read(0x20000000, 0x10000))
        self.emu.emu_start(self.symbols[name] | 1, RETURN, timeout=1_000_000, count=250_000)
        self.checked_ram(before)
        self.assertEqual(self.emu.reg_read(UC_ARM_REG_PC), RETURN, name + " must return within budget")
        self.assertEqual(self.emu.reg_read(UC_ARM_REG_SP), STACK, name + " stack ABI")
        self.assertEqual([self.emu.reg_read(register) for register in SAVED], expected_saved,
                         name + " callee-saved ABI")
        self.assertEqual(bytes(self.emu.mem_read(STATE - 16, 16)), b"\xa5" * 16)
        self.assertEqual(bytes(self.emu.mem_read(STATE + 640, 16)), b"\x5a" * 16)
        return self.emu.reg_read(UC_ARM_REG_R0)

    def peek(self, now):
        token = self.call("sf_tx_peek", STATE, now, OUTPUT)
        if not token:
            return None
        tick, epoch, report_id, length, data, copied_token = struct.unpack(
            "<IHBB8sI", self.emu.mem_read(OUTPUT, 20))
        self.assertEqual(token, copied_token)
        self.assertIn(report_id, (1, 2))
        self.assertEqual(length, 8 if report_id == 1 else 3)
        return {"tick": tick, "epoch": epoch, "id": report_id,
                "data": data[:length], "token": token}

    def complete(self, view, now, result=0):
        self.assertEqual(self.call("sf_tx_complete", STATE, view["token"], result, now), 1)

    def neutral(self, now):
        view = self.peek(now)
        self.assertIsNotNone(view)
        self.assertEqual(view["data"], bytes(len(view["data"])))
        self.complete(view, now)
        return view

    def ready(self, now=0, peer=0x12345678):
        self.call("sf_link", STATE, 1, peer, now)
        self.call("sf_cccd", STATE, 3, now)
        self.assertEqual({self.neutral(now)["id"], self.neutral(now)["id"]}, {1, 2})

    def submit(self, report_id, data, now):
        self.emu.mem_write(INPUT, data)
        return self.call("sf_submit", STATE, report_id, len(data), INPUT, now)

    def source_push(self, kind, count, payload):
        self.emu.mem_write(INPUT, struct.pack("<BB5sB", kind, count, payload, 0))
        return self.call("sf_source_push", STATE, INPUT)

    def source_pop(self):
        if not self.call("sf_source_pop", STATE, OUTPUT):
            return None
        return struct.unpack("<BB5sB", self.emu.mem_read(OUTPUT, 8))

    def uart(self, data):
        self.emu.mem_write(INPUT, data)
        return self.call("sf_uart_feed", STATE, INPUT, len(data))

    def test_thumb_ram_guard_rejects_real_store_outside_reviewed_ranges(self):
        # Real Thumb STRB r1,[r0]; BX lr. Probe after both state sentinels, so
        # this must be caught by the complete RAM check rather than a sentinel.
        probe, address = 0x1000, STATE + 640 + 16
        self.emu.mem_write(probe, bytes.fromhex("01707047"))
        self.symbols = dict(self.symbols, ram_guard_probe=probe | 1)
        with self.assertRaisesRegex(AssertionError,
                f"Core wrote outside reviewed state/arguments/stack: {address:#x}"):
            self.call("ram_guard_probe", address, 0x5A)
        self.assertEqual(bytes(self.emu.mem_read(address, 1)), b"\x5a")
        for protected in (probe, RETURN):
            with self.subTest(protected=hex(protected)):
                before = bytes(self.emu.mem_read(protected, 1))
                with self.assertRaises(UcError) as rejected:
                    self.call("ram_guard_probe", protected, 0x5A)
                self.assertEqual(rejected.exception.errno, UC_ERR_WRITE_PROT)
                self.assertEqual(bytes(self.emu.mem_read(protected, 1)), before)

    def test_thumb_state_layout_full_source_fifo_and_overflow_neutralization(self):
        self.ready()
        size = self.call("sf_core_size", STATE)
        self.assertGreater(size, 16 * 8 + 16 * 16)
        self.assertLessEqual(size, 640)
        for index in range(16):
            self.assertEqual(self.source_push(4, 5, bytes([index, 1, 2, 3, 4])), 1)
        for index in range(16):
            self.assertEqual(self.source_pop(), (4, 5, bytes([index, 1, 2, 3, 4]), 0))
        self.assertIsNone(self.source_pop())
        for _ in range(16):
            self.assertEqual(self.source_push(4, 5, b"abcde"), 1)
        self.assertEqual(self.source_push(4, 5, b"abcde"), 0)
        self.assertIsNone(self.source_pop())  # uncertain source history is discarded
        self.assertEqual({self.neutral(1)["id"], self.neutral(1)["id"]}, {1, 2})
        self.assertEqual(self.source_push(4, 6, b"abcde"), 0)
        self.assertIsNone(self.source_pop())

    def test_thumb_parser_fragments_embedded_fe_resync_and_all_index_bounds(self):
        frame = bytes([0xFE, 1, 1, 36, 0xFE, 0])
        self.assertEqual(self.uart(frame[:2]), 0)
        self.assertEqual(self.uart(frame[2:]), 1)
        self.assertEqual(self.source_pop(), (3, 5, frame[1:], 0))
        self.assertEqual(self.uart(bytes([0xFE, 0, 7, 0xFE, 0, 1])), 0)
        self.assertEqual(self.uart(bytes([24, 0, 0])), 1)
        self.assertEqual(self.source_pop()[2], bytes([0, 1, 24, 0, 0]))
        self.assertEqual(self.uart(bytes([0xFE, 0, 1, 45, 0, 0])), 0)
        self.assertEqual(self.uart(frame), 1)
        self.assertEqual(self.source_pop()[2], frame[1:])
        for index in range(256):
            self.assertEqual(self.call("sf_front_index_valid", STATE, index), int(index < 45 or index == 255))

    def test_thumb_release_retry_keeps_obligation_and_backs_off_until_event(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x45\0\0", 100), 0)
        press = self.peek(100)
        self.complete(press, 100)
        self.assertEqual(self.submit(2, b"\0\0\0", 101), 0)
        now = 101
        for delay in (20, 50, 100, 200, 200):
            release = self.peek(now)
            self.assertEqual(release["data"], b"\0\0\0")
            self.complete(release, now, result=1)
            self.assertIsNone(self.peek(now + delay - 1))
            now += delay
        release = self.peek(2101)
        self.complete(release, 2101, result=1)
        self.assertIsNone(self.peek(50000))
        self.call("sf_wake", STATE, 50001)
        self.assertEqual(self.neutral(50001)["id"], 2)
        self.assertIsNone(self.peek(50001))
        # A second stale completion cannot pop or replay another event.
        self.assertEqual(self.call("sf_tx_complete", STATE, press["token"], 0, 50001), 0)

    def test_thumb_full_tx_fifo_protects_consumer_release_and_keyboard_order(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x45\0\0", 1), 0)
        self.complete(self.peek(1), 1)
        for index in range(16):
            self.assertEqual(self.submit(1, bytes([0, 0, 4 + index, 0, 0, 0, 0, 0]), 2), 0)
        self.assertEqual(self.submit(2, b"\0\0\0", 3), 0)
        self.assertEqual(self.submit(2, b"\x45\0\0", 3), 4)
        self.assertEqual(self.neutral(3)["id"], 2)
        for index in range(16):
            view = self.peek(3)
            self.assertEqual((view["id"], view["data"][2]), (1, 4 + index))
            self.complete(view, 3)
        self.assertIsNone(self.peek(3))

    def test_thumb_offline_taps_reconnect_ttl_and_epoch_reject_stale_completion(self):
        self.call("sf_link", STATE, 0, 0x12345678, 0)
        for now, key in ((1, 0x45), (2, 0), (3, 0x44), (4, 0), (5, 0x43), (6, 0)):
            self.assertEqual(self.submit(2, bytes([key, 0, 0]), now), 0)
        self.assertIsNone(self.peek(10))
        self.ready(10)
        for key in (0x45, 0, 0x44, 0, 0x43, 0):
            view = self.peek(10)
            self.assertEqual(view["data"], bytes([key, 0, 0]))
            self.complete(view, 10)
        self.assertEqual(self.submit(2, b"\x45\0\0", 20), 0)
        stale = self.peek(20)
        self.call("sf_link", STATE, 0, 0x12345678, 21)
        self.assertEqual(self.call("sf_tx_complete", STATE, stale["token"], 0, 22), 0)
        self.assertEqual(self.submit(2, b"\x44\0\0", 22), 0)
        self.assertEqual(self.submit(2, b"\0\0\0", 23), 0)
        self.ready(2022)
        self.assertEqual(self.neutral(2022)["id"], 2)  # old press expired; release survives
        self.assertIsNone(self.peek(2022))

    def test_thumb_peer_cccd_and_protocol_changes_never_replay_old_key(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x45\0\0", 1), 0)
        self.call("sf_link", STATE, 1, 0x22222222, 2)
        self.call("sf_cccd", STATE, 3, 2)
        self.neutral(2); self.neutral(2)
        self.assertIsNone(self.peek(2))
        self.assertEqual(self.submit(2, b"\x45\0\0", 3), 0)
        self.call("sf_cccd", STATE, 1, 4)
        self.assertIsNone(self.peek(4))
        self.assertEqual(self.submit(2, b"\x45\0\0", 4), 4)
        self.call("sf_cccd", STATE, 3, 5)
        self.assertEqual(self.neutral(5)["id"], 2)
        self.assertIsNone(self.peek(5))
        self.assertEqual(self.submit(2, b"\x45\0\0", 6), 0)
        self.call("sf_protocol", STATE, 0, 7)
        self.assertEqual(self.neutral(7)["id"], 1)
        self.assertIsNone(self.peek(7))
        self.call("sf_protocol", STATE, 1, 8)
        self.neutral(8); self.neutral(8)
        self.assertIsNone(self.peek(8))

    def test_thumb_keyboard_eight_bytes_and_unavailable_report_isolation(self):
        self.ready()
        first, second = b"\0\0\x04\x05\x06\0\0\0", b"\0\0\x04\x05\x07\0\0\0"
        self.assertEqual(self.submit(1, first, 1), 0)
        self.assertEqual(self.submit(1, second, 2), 0)
        self.assertEqual(self.submit(1, second, 2), 1)
        for expected in (first, second):
            view = self.peek(2)
            self.assertEqual(view["data"], expected)
            self.complete(view, 2)
        self.assertEqual(self.submit(1, first[:7], 3), 3)
        self.assertEqual(self.submit(2, first, 3), 3)
        self.assertEqual(self.submit(2, b"\x45\0\0", 3), 0)
        self.assertEqual(self.submit(1, first, 3), 0)
        blocked = self.peek(3)
        self.assertEqual(blocked["id"], 2)
        self.complete(blocked, 3, result=2)
        keyboard = self.peek(4)
        self.assertEqual(keyboard["data"], first)
        self.complete(keyboard, 4)
        self.assertIsNone(self.peek(4))
        self.call("sf_wake", STATE, 5)
        consumer = self.peek(5)
        self.assertEqual(consumer["data"], b"\x45\0\0")
        self.complete(consumer, 5)

    def test_thumb_millisecond_wrap_expires_old_press_but_keeps_release(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x45\0\0", 0xFFFFFF00), 0)
        self.assertEqual(self.submit(2, b"\0\0\0", 0xFFFFFF01), 0)
        # Unsigned elapsed time is exactly 2,000 ms across UINT32_MAX.
        self.assertEqual(self.neutral(0x6D0)["id"], 2)
        self.assertIsNone(self.peek(0x6D0))
        self.assertEqual(self.submit(2, b"\x45\0\0", 0x6D1), 0)
        fresh = self.peek(0x6D1)
        self.assertEqual((fresh["tick"], fresh["data"]), (0x6D1, b"\x45\0\0"))
        self.complete(fresh, 0x6D1)

    def test_thumb_accepted_power_press_has_one_flight_and_never_replays(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x30\0\0", 1), 0)
        self.assertEqual(self.submit(2, b"\0\0\0", 2), 0)
        power = self.peek(2)
        self.assertEqual(power["data"], b"\x30\0\0")
        self.assertIsNone(self.peek(2))
        self.assertEqual(self.call("sf_tx_complete", STATE, power["token"] + 1, 0, 2), 0)
        self.complete(power, 2)
        self.assertEqual(self.call("sf_tx_complete", STATE, power["token"], 1, 2), 0)
        self.assertEqual(self.neutral(2)["id"], 2)
        self.call("sf_wake", STATE, 3000)
        self.assertIsNone(self.peek(3000))

    def test_thumb_initial_neutrals_preserve_latest_fresh_fifo_state_for_both_reports(self):
        self.call("sf_link", STATE, 1, 0x12345678, 0)
        self.call("sf_cccd", STATE, 3, 0)
        keyboard, power = b"\0\0\x04\0\0\0\0\0", b"\x30\0\0"
        for report, data in ((1, keyboard), (2, power)):
            self.assertEqual(self.submit(report, data, 1), 0)
        self.neutral(2); self.neutral(2)
        for report, data in ((1, keyboard), (2, power)):
            self.assertEqual(self.submit(report, data, 2), 1)
            view = self.peek(2)
            self.assertEqual((view["id"], view["data"]), (report, data))
            self.complete(view, 2)
            self.assertEqual(self.submit(report, data, 3), 1)
        self.assertIsNone(self.peek(3))
        # Preserve the last queued release rather than an older Power: the
        # following physical press is a new action even before TX catches up.
        self.assertEqual(self.submit(2, bytes(3), 4), 0)
        self.assertEqual(self.submit(2, power, 5), 0)
        self.neutral(5)
        self.assertEqual(self.peek(5)["data"], power)

    def test_thumb_repair_completion_does_not_restore_expired_or_old_epoch_admission(self):
        self.call("sf_link", STATE, 1, 0x12345678, 0)
        self.call("sf_cccd", STATE, 3, 0)
        self.assertEqual(self.submit(2, b"\x30\0\0", 1), 0)
        self.neutral(1)
        repair = self.peek(1)
        self.assertEqual(repair["data"], bytes(3))
        self.complete(repair, 2001)
        self.assertEqual(self.submit(2, b"\x30\0\0", 2001), 0)
        fresh = self.peek(2001)
        self.assertEqual((fresh["tick"], fresh["data"]), (2001, b"\x30\0\0"))
        self.complete(fresh, 2001)
        self.assertIsNone(self.peek(2001))
        self.call("sf_link", STATE, 1, 0x11223344, 2002)
        self.call("sf_cccd", STATE, 3, 2002)
        self.neutral(2002); self.neutral(2002)
        self.assertEqual(self.submit(2, b"\x30\0\0", 2003), 0)

    def test_thumb_expiring_old_press_preserves_newer_valid_pending_press_dedupe(self):
        self.ready()
        self.assertEqual(self.submit(2, b"\x30\0\0", 0), 0)
        self.assertEqual(self.submit(2, bytes(3), 1000), 0)
        self.assertEqual(self.submit(2, b"\x30\0\0", 1900), 0)
        self.assertEqual(self.submit(2, b"\x30\0\0", 2100), 1)
        self.neutral(2100)
        fresh = self.peek(2100)
        self.assertEqual((fresh["tick"], fresh["data"]), (1900, b"\x30\0\0"))
        self.complete(fresh, 2100)
        self.assertIsNone(self.peek(2100))


if __name__ == "__main__":
    unittest.main()
