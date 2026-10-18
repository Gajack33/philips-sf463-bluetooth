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


class DiagnosticDecoderTests(unittest.TestCase):
    def test_three_pages_decode_little_endian_fields_units_and_cli_without_connections(self):
        values = pages()
        report = decoder.decode_pages("GVK1EH_B002FFv.06.09", [values[2], values[0], values[1]])
        self.assertEqual(report["status"], "active")
        self.assertTrue(report["improvements_active"])
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
        for version in ("06.07", "06.10", "06.08", "", "GVK1EH_B002FFv.06.10", "07.09"):
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
        for bad in ("0100" + "0" * 16, "00000001000000000000"):
            with self.subTest(page=bad), self.assertRaises(ValueError):
                decoder.decode_pages("06.09", [bad])


if __name__ == "__main__":
    unittest.main()
