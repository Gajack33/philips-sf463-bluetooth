"""Offline page decoder checks; no hardware or persistent GATT client."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "decode_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("sf463_diagnostic_decoder", PATH)
decoder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decoder)


def pages():
    return [struct.pack("<BBHHHH", 0, 1, 900, 2, 3, 5).hex().upper(),
            struct.pack("<BBII", 1, 1, 1200, 800).hex().upper(),
            struct.pack("<BBIBBBB", 2, 1, 400, 0, 3, 6, 0x87).hex().upper()]


def inactive(reason, bond=0xFF, free=0xFFFF, largest=0xFFFF, flags=0, role=6):
    return struct.pack("<BBBBHHBB", 0, 0, reason, bond, free, largest, flags, role).hex().upper()


class DiagnosticDecoderTests(unittest.TestCase):
    def test_quiescence_refusal_distinguishes_prequery_and_final_allocation_samples(self):
        prequery = decoder.decode_pages("6.095", [inactive(11, flags=1)])["fallback"]
        self.assertEqual(prequery["reason"], "native_transmission_not_quiescent")
        self.assertIsNone(prequery["bond_count"])
        self.assertIsNone(prequery["heap"])
        final = decoder.decode_pages("6.095", [inactive(11, 1, 768, 300, 1)])["fallback"]
        self.assertEqual(final["heap"], {"free_bytes": 768, "largest_free_block_bytes": 300,
                                         "sample_phase": "post_allocation_before_release"})
        for invalid in (inactive(11, 1, flags=1), inactive(11, 1, 767, 300, 1),
                        inactive(11, 255, 768, 300, 1), inactive(11, 1, 768, 0xFFFF, 1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decoder.decode_pages("6.095", [invalid])

    def test_three_pages_decode_little_endian_fields_units_and_cli_without_connections(self):
        values = pages()
        report = decoder.decode_pages("GVK1EH_B002FFv.06.09", [values[2], values[0], values[1]])
        self.assertEqual(report["status"], "active")
        self.assertTrue(report["improvements_active"])
        self.assertNotIn("fallback", report)
        self.assertEqual(report["memory"], {"minimum_sampled_free_bytes": 900})
        self.assertEqual(report["events"], {"source_dropped_low16": 2, "tx_dropped_low16": 3,
            "retries_low16": 5, "tx_pending": 7, "repair_mask": 3, "last_front_index": None})
        self.assertEqual(report["activity"], {"connected_ms": 1200, "uart_logical_active_ms": 800,
                                             "uart_logical_inactive_ms": 400})
        self.assertEqual(report["link"], {"role_state": 6, "identity_verified": True})
        self.assertTrue(any("not a continuous" in value for value in report["limitations"]))
        self.assertTrue(any("not establish battery" in value for value in report["limitations"]))
        cli = subprocess.run([sys.executable, str(PATH), "--firmware-version", "06.09", *values],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), report)

    def test_version_mismatch_and_non_twenty_character_hex_are_rejected(self):
        for version in ("06.07", "06.10", "06.08", "", "GVK1EH_B002FFv.06.10", "07.09",
                        "6.09", "06.095", "6.0950", "GVK1EH_B002FFv.6.0950"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "Only diagnostic"):
                decoder.decode_pages(version, pages())
        for bad in ("", "0" * 19, "0" * 21, "G" * 20, "00 10000000000000000"):
            values = pages(); values[0] = bad
            with self.subTest(page=bad), self.assertRaisesRegex(ValueError, "20 hexadecimal"):
                decoder.decode_pages("06.09", values)
        cli = subprocess.run([sys.executable, str(PATH), "--firmware-version", "06.10", *pages()],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 2)
        self.assertEqual(cli.stdout, "")

    def test_rc2_exact_twenty_byte_header_explicit_version_and_cli_preserve_actual_version(self):
        full_version = "GVK1EH_B002FFv.6.095"
        self.assertEqual(len(full_version.encode("ascii")), 20)
        self.assertEqual(len("GVK1EH_B002FFv.06.09".encode("ascii")), 20)
        native_float = lambda value: struct.unpack("<f", struct.pack("<f", float(value)))[0]
        self.assertLess(native_float("06.09"), native_float("6.095"))
        self.assertLess(native_float("6.095"), native_float("06.10"))
        captures = (pages(), [inactive(9, 1, 768, 300, 3)], ["0" * 20])
        for supplied_version in ("6.095", full_version):
            for captured in captures:
                with self.subTest(version=supplied_version, captures=captured):
                    expected = decoder.decode_pages("06.09", captured)
                    expected["firmware_version"] = "6.095"
                    self.assertEqual(decoder.decode_pages(supplied_version, captured), expected)
                    cli = subprocess.run([sys.executable, str(PATH), "--firmware-version", supplied_version, *captured],
                                         capture_output=True, text=True)
                    self.assertEqual(cli.returncode, 0, cli.stderr)
                    self.assertEqual(json.loads(cli.stdout), expected)

    def test_page_identity_activation_and_known_schema_bounds_are_checked(self):
        for values in ([pages()[0]], pages()[:2], [pages()[0]] * 3,
                       ["0301" + "0" * 16, *pages()[1:]],
                       ["0002" + "0" * 16, *pages()[1:]],
                       [bytes(10).hex(), *pages()[1:]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", values)
        for front_index, repair, packed in ((0, 0, 0x91), (0, 4, 0x81), (0, 0, 0xA0),
                                           (45, 0, 0xC1), (255, 0, 0xC1)):
            values = pages()
            values[2] = struct.pack("<BBIBBBB", 2, 1, 400, front_index, repair, 6, packed).hex()
            with self.subTest(index=front_index, repair=repair, packed=packed), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", values)

    def test_last_front_index_packed_flags_distinguish_known_unknown_and_identity(self):
        for index, verified, pending in ((0, False, 0), (38, True, 7), (44, False, 16)):
            values = pages()
            packed = (0x80 if verified else 0) | 0x40 | pending
            values[2] = struct.pack("<BBIBBBB", 2, 1, 400, index, 3, 6, packed).hex()
            report = decoder.decode_pages("06.09", values)
            self.assertEqual(report["events"]["last_front_index"], index)
            self.assertEqual(report["events"]["tx_pending"], pending)
            self.assertIs(report["link"]["identity_verified"], verified)
        values = pages()
        values[2] = struct.pack("<BBIBBBB", 2, 1, 400, 255, 0, 6, 0x87).hex()
        unknown = decoder.decode_pages("06.09", values)
        self.assertIsNone(unknown["events"]["last_front_index"])
        self.assertEqual(unknown["events"]["tx_pending"], 7)
        self.assertTrue(unknown["link"]["identity_verified"])

    def test_native_fallback_is_explicit_and_does_not_present_fake_zero_metrics(self):
        for values in (["0" * 20], ["0" * 20] * 3):
            report = decoder.decode_pages("06.09", values)
            self.assertEqual(report["status"], "fallback_inactive")
            self.assertFalse(report["improvements_active"])
            self.assertEqual([report[key] for key in ("memory", "activity", "events", "link")], [None] * 4)
            self.assertIn("not initialized", report["message"])
            self.assertEqual(report["fallback"], {"reason_code": 0, "reason": "unknown", "bond_count": None,
                "heap": None, "flags": {"raw": None, "hid_semaphore_present": None,
                    "hid_queue_busy": None, "app_front_pending": None, "app_rear_pending": None},
                "role_state": None, "legacy_all_zero": True})
        for bad in ("0100" + "0" * 16, "00000001000000000000"):
            with self.subTest(page=bad), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", [bad])

    def test_detailed_fallback_decodes_exact_snapshot_without_active_metrics(self):
        value = inactive(10, bond=1, free=0x0321, largest=0x0123, flags=0x0D, role=6)
        report = decoder.decode_pages("GVK1EH_B002FFv.06.09", [value] * 3)
        self.assertEqual(report["status"], "fallback_inactive")
        self.assertFalse(report["improvements_active"])
        self.assertEqual([report[key] for key in ("memory", "activity", "events", "link")], [None] * 4)
        self.assertEqual(report["fallback"], {"reason_code": 10, "reason": "app_mailbox_busy", "bond_count": 1,
            "heap": {"free_bytes": 801, "largest_free_block_bytes": 291,
                     "sample_phase": "post_allocation_before_release"},
            "flags": {"raw": 0x0D, "hid_semaphore_present": True, "hid_queue_busy": False,
                      "app_front_pending": True, "app_rear_pending": True},
            "role_state": 6, "legacy_all_zero": False})
        cli = subprocess.run([sys.executable, str(PATH), "--firmware-version", "06.09", value],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), report)

    def test_fallback_reasons_and_unknown_sentinels_keep_raw_role_and_named_flags(self):
        fixtures = [
            (inactive(0, flags=0x0F, role=0xE6), "unknown", None, None),
            (inactive(1), "hid_semaphore_missing", None, None),
            (inactive(2, bond=0, flags=1), "bond_count_not_one", 0, None),
            (inactive(2, bond=2, flags=1), "bond_count_not_one", 2, None),
            (inactive(2, bond=255, flags=1), "bond_count_not_one", None, None),
            (inactive(3, bond=1, flags=1), "bond_identity_rpc_failed", 1, None),
            (inactive(4, bond=1, flags=1), "zero_bond_identity", 1, None),
            (inactive(5, bond=1, free=1415, largest=640, flags=1), "insufficient_total_free", 1, "pre_allocation"),
            (inactive(6, bond=1, free=1416, largest=639, flags=1), "insufficient_largest_block", 1, "pre_allocation"),
            (inactive(7, bond=1, free=1416, largest=640, flags=1), "allocation_failed", 1, "pre_allocation"),
            (inactive(8, bond=1, free=767, largest=300, flags=1), "insufficient_post_allocation_free", 1,
             "post_allocation_before_release"),
            (inactive(9, bond=1, free=768, largest=300, flags=3), "hid_queue_busy", 1,
             "post_allocation_before_release"),
            (inactive(10, bond=1, free=768, largest=300, flags=5), "app_mailbox_busy", 1,
             "post_allocation_before_release"),
        ]
        for value, reason, bonds, phase in fixtures:
            with self.subTest(reason=reason, value=value):
                result = decoder.decode_pages("06.09", [value])["fallback"]
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["bond_count"], bonds)
                self.assertFalse(result["legacy_all_zero"])
                if phase is None:
                    self.assertIsNone(result["heap"])
                else:
                    self.assertEqual(result["heap"]["sample_phase"], phase)
        unknown = decoder.decode_pages("06.09", [fixtures[0][0]])["fallback"]
        self.assertEqual(unknown["role_state"], 0xE6)  # Raw HID byte, never split into nibbles.
        self.assertEqual(unknown["flags"], {"raw": 15, "hid_semaphore_present": True,
            "hid_queue_busy": True, "app_front_pending": True, "app_rear_pending": True})

    def test_fallback_thresholds_reject_contradictions_without_preallocation_checks_on_post_stats(self):
        # These post-allocation free/block sizes are below the pre-allocation limits and remain valid.
        for value, free, largest in ((inactive(8, 1, 500, 400, 1), 500, 400),
                                     (inactive(9, 1, 768, 32, 3), 768, 32),
                                     (inactive(10, 1, 900, 16, 9), 900, 16)):
            with self.subTest(value=value):
                heap = decoder.decode_pages("06.09", [value])["fallback"]["heap"]
                self.assertEqual(heap, {"free_bytes": free, "largest_free_block_bytes": largest,
                                       "sample_phase": "post_allocation_before_release"})
        contradictions = [inactive(5, 1, 1416, 640, 1), inactive(6, 1, 1415, 639, 1),
                          inactive(6, 1, 1416, 640, 1), inactive(7, 1, 1415, 640, 1),
                          inactive(7, 1, 1416, 639, 1), inactive(8, 1, 768, 300, 1),
                          inactive(9, 1, 767, 300, 3), inactive(10, 1, 767, 300, 5),
                          inactive(8, 1, 500, 501, 1)]
        for value in contradictions:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "contradict"):
                decoder.decode_pages("06.09", [value])

    def test_fallback_rejects_reserved_reason_flags_pages_and_inconsistent_guard_evidence(self):
        malformed = [inactive(11), inactive(0, flags=0x10), inactive(0, flags=0xFF),
                     inactive(0, bond=1), inactive(0, free=0), inactive(1, free=0),
                     inactive(1, flags=1), inactive(1, bond=1),
                     inactive(2, bond=1, flags=1), inactive(2, bond=0),
                     inactive(3, bond=0, flags=1), inactive(4, flags=1),
                     inactive(5, 1, 1000, 0xFFFF, 1), inactive(5, 1, 0xFFFF, 300, 1),
                     inactive(9, 1, 768, 300, 1), inactive(10, 1, 768, 300, 1),
                     inactive(10, 1, 768, 300, 0x0F)]
        valid = inactive(10, 1, 801, 291, 0x0D)
        malformed.extend(["01" + valid[2:], "02" + valid[2:]])
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", [value])

    def test_fallback_snapshots_must_agree_and_cli_still_requires_explicit_0609_version(self):
        value = inactive(9, 1, 768, 300, 3)
        for values in ([value] * 2, [value, value, inactive(9, 1, 768, 300, 3, 5)],
                       [value, "0" * 20, value]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", values)
        self.assertEqual(decoder.decode_pages("06.09", [value]), decoder.decode_pages("06.09", [value] * 3))
        for arguments in ([value], ["--firmware-version", "06.10", value],
                          ["--firmware-version", "06.07", value]):
            with self.subTest(arguments=arguments):
                cli = subprocess.run([sys.executable, str(PATH), *arguments], capture_output=True, text=True)
                self.assertEqual(cli.returncode, 2)
                self.assertEqual(cli.stdout, "")


if __name__ == "__main__":
    unittest.main()
