"""Integrity and negative-path checks against the immutable real stock image."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

MODULE_PATH = Path(__file__).resolve().parents[1] / "build.py"
SPEC = importlib.util.spec_from_file_location("sf463_image_build", MODULE_PATH)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
ROOT = MODULE_PATH.parents[1]
STOCK = (ROOT / "firmware/original/GVK1EH_B002FFv.06.05.bin").read_bytes()
BASELINE = (ROOT / "firmware/RCFW/GVK1EH_B002FFv.06.07.bin").read_bytes()


def manifest():
    # Synthetic patch layout: these tests qualify builder invariants, not a firmware integration.
    rules = {"schema": 1, "integration_qualified": True,
            "allowed_ranges": [
                {"name": "gate", "start": "0x1d28", "end": "0x1d2a", "category": "front"},
                {"name": "consumer", "start": "0x21dc", "end": "0x21e0", "category": "hid"},
                {"name": "diagnostic", "start": "0x5250", "end": "0x5254", "category": "diagnostic"}],
            "hooks": [
                {"name": "front-gate", "offset": "0x1d28", "expected_hex": "05d1",
                 "kind": "bytes", "replacement_hex": "00bf", "category": "front"},
                {"name": "consumer", "offset": "0x21dc", "expected_hex": STOCK[0x21DC:0x21E0].hex(),
                 "kind": "branch", "symbol": "entry", "link": False, "category": "hid"},
                {"name": "snapshot", "offset": "0x5250", "expected_hex": STOCK[0x5250:0x5254].hex(),
                 "kind": "branch", "symbol": "entry", "link": False,
                 "category": "diagnostic", "variants": ["diagnostic"]}]}
    images = {}
    for variant in ("usage", "diagnostic"):
        image, _ = build.apply_image(STOCK, BASELINE, rules, variant, b"\x00\xbf\x70\x47",
                                     {"entry": 0x17001}, require_qualified=False)
        images[variant] = build.digest(image)
    evidence = build.ROOT / "evidence/builder-fixture.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"scope": "synthetic builder fixture; not hardware or adapter proof",
                                    "passed": True, "inputs_unchanged": True,
                                    "sources": build.source_hashes(),
                                    "integration_hook_sha256": build.hook_digest(rules),
                                    "stages": [{"name": "synthetic-builder-fixture",
                                                "passed": True, "exit_code": 0}],
                                    "variant_images": images}), encoding="utf-8")
    rules["integration_sources"] = build.source_hashes()
    rules["integration_hook_sha256"] = build.hook_digest(rules)
    rules["integration_evidence"] = [{"path": "evidence/builder-fixture.json",
                                      "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]
    return rules


def elf_fixture(address=0x17000, flags=6, kind=1):
    data = bytearray(0x200)
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<HHI", data, 16, 2, 40, 1)
    struct.pack_into("<I", data, 32, 0x100)
    struct.pack_into("<HHH", data, 46, 40, 4, 0)
    # null, code, symbol table, string table
    struct.pack_into("<10I", data, 0x128, 0, kind, flags, address, 0x80, 4, 0, 0, 4, 0)
    struct.pack_into("<10I", data, 0x150, 0, 2, 0, 0, 0x90, 16, 3, 0, 4, 16)
    struct.pack_into("<10I", data, 0x178, 0, 3, 0, 0, 0xA0, 7, 0, 0, 1, 0)
    data[0x80:0x84] = b"\x00\xbf\x70\x47"
    struct.pack_into("<IIIBBH", data, 0x90, 1, address | 1, 4, 0x12, 0, 1)
    data[0xA0:0xA7] = b"\x00entry\x00"
    return bytes(data)


class ImageBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sf463-builder-fixture-")
        self.addCleanup(temporary.cleanup)
        fixture_root = Path(temporary.name)
        for source in build.source_files():
            target = fixture_root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        patch = mock.patch.object(build, "ROOT", fixture_root)
        patch.start()
        self.addCleanup(patch.stop)

    def make(self, rules=None, variant="usage", payload=b"\x00\xbf\x70\x47", **kwargs):
        return build.apply_image(STOCK, BASELINE, rules or manifest(), variant, payload,
                                 {"entry": 0x17001}, **kwargs)

    def test_real_inputs_are_fixed_and_corruptions_fail_closed(self):
        build.validate_inputs(STOCK, BASELINE)
        self.assertEqual(len(STOCK), 118784)
        for label, source in (("stock", STOCK), ("baseline", BASELINE)):
            changed = bytearray(source)
            changed[0x3000] ^= 1
            with self.subTest(label=label), self.assertRaises(build.BuildError):
                build.validate_inputs(bytes(changed) if label == "stock" else STOCK,
                                      bytes(changed) if label == "baseline" else BASELINE)

    def test_usage_image_preserves_metadata_native_diagnostic_and_unlisted_bytes(self):
        image, patches = self.make()
        self.assertEqual(image[0x16E0:0x16F4], b"GVK1EH_B002FFv.06.10")
        self.assertEqual(image[0x52B2:0x52B6], STOCK[0x52B2:0x52B6])
        self.assertEqual(image[0x5250:0x5254], STOCK[0x5250:0x5254])
        self.assertEqual(image[2:0x100], STOCK[2:0x100])
        self.assertEqual(image[0x1D28:0x1D2A], b"\x00\xbf")
        self.assertEqual(image[0x17000:0x17004], b"\x00\xbf\x70\x47")
        self.assertEqual(struct.unpack_from("<H", image)[0], build.crc(image))
        self.assertEqual(len(image), len(STOCK))
        self.assertEqual(len(patches), 2)
        allowed = [(0, 2), (0x16E0, 0x16F4), (0x1D28, 0x1D2A), (0x21DC, 0x21E0), (0x17000, 0x17004)]
        for index, (before, after) in enumerate(zip(STOCK, image)):
            if before != after:
                self.assertTrue(any(start <= index < end for start, end in allowed), hex(index))

    def test_declared_blue_fix_is_one_flash_byte_and_preserves_the_other_44_rows(self):
        actual = json.loads((MODULE_PATH.parent / "hooks.json").read_text(encoding="utf-8"))
        hook = next(item for item in actual["hooks"]
                    if item["name"] == "physical-blue-primary-consumer-usage")
        permitted = next(item for item in actual["allowed_ranges"]
                         if int(item["start"], 0) == 0x13BF0)
        self.assertEqual(hook, {"name": "physical-blue-primary-consumer-usage",
            "offset": "0x13bf0", "expected_hex": "6c", "kind": "bytes",
            "replacement_hex": "6b", "category": "front"})
        self.assertEqual(permitted, {"start": "0x13bf0", "end": "0x13bf1", "category": "front"})
        start, end = 0x13B84, 0x13B84 + 45 * 4
        table = STOCK[start:end]
        self.assertEqual(BASELINE[start:end], table)
        self.assertEqual(len(table), 180)
        self.assertEqual(STOCK.count(table), 1)
        self.assertEqual(STOCK.find(table), start)
        self.assertEqual(STOCK.count(bytes.fromhex("6c006bf0")), 1)
        self.assertGreater(0x13BF0, 0x10000)  # A first-64KiB capture cannot contain it.
        self.assertEqual(len(STOCK), 118784)
        for variant in ("usage", "diagnostic"):
            with self.subTest(variant=variant):
                rules = manifest()
                before, _ = self.make(rules, variant, require_qualified=False)
                rules["allowed_ranges"].append(copy.deepcopy(permitted))
                rules["hooks"].append(copy.deepcopy(hook))
                after, patches = self.make(rules, variant, require_qualified=False)
                self.assertEqual(after[0x13BF0:0x13BF4], bytes.fromhex("6b006bf0"))
                self.assertEqual([i for i, (a, b) in enumerate(zip(before, after))
                                  if a != b and i >= 2], [0x13BF0])
                self.assertEqual(struct.unpack_from("<H", after)[0], build.crc(after))
                self.assertEqual(len(after), len(before))
                for index in range(45):
                    row = start + index * 4
                    expected = bytes.fromhex("6b006bf0") if index == 0x1B else STOCK[row:row + 4]
                    self.assertEqual(after[row:row + 4], expected, f"front row {index:#x}")
                self.assertEqual(patches[-1], {"name": hook["name"], "offset": "0x13bf0",
                                               "before": "6c", "after": "6b", "category": "front"})

    def test_blue_patch_rejects_wrong_expected_byte_and_neighboring_table_writes(self):
        for mutation in ("wrong expected", "neighbor", "extend row"):
            with self.subTest(mutation=mutation):
                rules = manifest()
                rules["allowed_ranges"].append({"start": "0x13bf0", "end": "0x13bf1", "category": "front"})
                hook = {"name": "blue-negative", "offset": "0x13bf0", "expected_hex": "6c",
                        "kind": "bytes", "replacement_hex": "6b", "category": "front"}
                if mutation == "wrong expected":
                    hook["expected_hex"] = "6b"
                elif mutation == "neighbor":
                    hook.update(offset="0x13bf1", expected_hex="00", replacement_hex="01")
                else:
                    hook.update(expected_hex="6c00", replacement_hex="6b00")
                rules["hooks"].append(hook)
                with self.assertRaises(build.BuildError):
                    self.make(rules, require_qualified=False)

    def test_diagnostic_has_distinct_revision_and_explicit_callback_branch(self):
        image, _ = self.make(variant="diagnostic")
        self.assertEqual(image[0x16E0:0x16F4], b"GVK1EH_B002FFv.6.097")
        self.assertNotEqual(image[0x5250:0x5254], STOCK[0x5250:0x5254])
        self.assertEqual(image[0x52B2:0x52B6], STOCK[0x52B2:0x52B6])
        rules = manifest()
        rules["hooks"] = rules["hooks"][:2]
        with self.assertRaisesRegex(build.BuildError, "Diagnostic"):
            self.make(rules, variant="diagnostic", require_qualified=False)

    def test_intermediate_diagnostic_revision_fits_native_string_and_float_order(self):
        # Philips compares the suffix with Java Float.parseFloat and strict >.
        previous, intermediate, final = "6.096", build.VERSIONS["diagnostic"], build.VERSIONS["usage"]
        binary32 = lambda value: struct.unpack("<f", struct.pack("<f", float(value)))[0]
        self.assertLess(binary32(previous), binary32(intermediate))
        self.assertLess(binary32(intermediate), binary32(final))
        for version in (previous, intermediate, final):
            with self.subTest(version=version):
                self.assertEqual(len(f"GVK1EH_B002FFv.{version}".encode("ascii")), 20)
        image, _ = self.make(variant="diagnostic")
        with tempfile.TemporaryDirectory() as directory:
            assets = build.write_assets(Path(directory), "diagnostic", image, {"hardware_validated": False})
            self.assertEqual(assets[0].name, "GVK1EH_B002FFv.6.097.bin")
            self.assertEqual(assets[1].name, "SF463-6.097-diagnostic-USB.zip")
            with zipfile.ZipFile(assets[1]) as package:
                self.assertEqual(package.namelist(), ["RCFW/GVK1EH_B002FFv.6.097.bin"])
                self.assertEqual(package.read(package.namelist()[0]), image)

    def test_unqualified_or_stale_evidence_never_generates_an_image(self):
        rules = manifest()
        rules["integration_qualified"] = False
        with self.assertRaisesRegex(build.BuildError, "not qualified"):
            self.make(rules)
        # Check-only deliberately audits the complete byte transformation without packaging.
        image, _ = self.make(rules, require_qualified=False)
        self.assertEqual(image[0x1D28:0x1D2A], b"\x00\xbf")
        rules = manifest()
        rules["integration_evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(build.BuildError, "evidence hash mismatch"):
            self.make(rules)
        rules["integration_evidence"] = []
        with self.assertRaisesRegex(build.BuildError, "hashed evidence"):
            self.make(rules)

    def test_instruction_mismatch_category_bounds_and_overlap_are_rejected(self):
        cases = []
        rules = manifest(); rules["hooks"][0]["expected_hex"] = "04d1"; cases.append(rules)
        rules = manifest(); rules["allowed_ranges"][0]["end"] = "0x1d29"; cases.append(rules)
        rules = manifest(); rules["hooks"][0]["category"] = "ota"; cases.append(rules)
        rules = manifest(); rules["hooks"].append(copy.deepcopy(rules["hooks"][0])); cases.append(rules)
        rules = manifest(); rules["hooks"][0]["replacement_hex"] = "00bf00bf"; cases.append(rules)
        rules = manifest(); rules["protected_ranges"] = [{"start": "0x1d28", "end": "0x1d2a"}]; cases.append(rules)
        for index, rules in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(build.BuildError):
                self.make(rules, require_qualified=False)

    def test_qualification_rejects_changed_source_missing_input_and_changed_hooks(self):
        rules = manifest()
        source = build.ROOT / "firmware/adapter.c"
        original = source.read_bytes()
        source.write_bytes(original + b"\n/* changed after qualification */\n")
        with self.assertRaisesRegex(build.BuildError, "source binding mismatch"):
            self.make(rules)
        source.write_bytes(original)
        rules["integration_sources"].pop("firmware/adapter.c")
        with self.assertRaisesRegex(build.BuildError, "source binding mismatch"):
            self.make(rules)
        rules = manifest()
        # The new allowlist is structurally valid, but was never qualified.
        rules["allowed_ranges"][1]["end"] = "0x21e2"
        with self.assertRaisesRegex(build.BuildError, "hook binding mismatch"):
            self.make(rules)

    def test_qualification_rejects_wrong_variant_image_even_with_valid_evidence_hash(self):
        rules = manifest()
        evidence = build.ROOT / rules["integration_evidence"][0]["path"]
        proof = json.loads(evidence.read_text())
        proof["variant_images"]["usage"] = "0" * 64
        evidence.write_text(json.dumps(proof), encoding="utf-8")
        rules["integration_evidence"][0]["sha256"] = build.digest(evidence.read_bytes())
        with self.assertRaisesRegex(build.BuildError, "image binding mismatch"):
            self.make(rules)
        # A different compiled payload cannot inherit the previous proof.
        rules = manifest()
        with self.assertRaisesRegex(build.BuildError, "image binding mismatch"):
            self.make(rules, payload=b"\x01\x20\x70\x47")

    def test_qualification_rejects_failed_unstable_or_incomplete_proof_with_valid_hash(self):
        cases = [
            ("missing passed", "passed", None),
            ("failed suite", "passed", False),
            ("nonboolean passed", "passed", 1),
            ("missing input stability", "inputs_unchanged", None),
            ("unstable inputs", "inputs_unchanged", False),
            ("nonboolean input stability", "inputs_unchanged", "true"),
            ("missing sources", "sources", None),
            ("wrong sources", "sources", {"firmware/adapter.c": "0" * 64}),
            ("missing hook digest", "integration_hook_sha256", None),
            ("wrong hook digest", "integration_hook_sha256", "0" * 64),
            ("missing stages", "stages", None),
            ("empty stages", "stages", []),
            ("stages not list", "stages", {}),
            ("stage not object", "stages", [None]),
            ("stage missing passed", "stages", [{"exit_code": 0}]),
            ("failed stage", "stages", [{"passed": False, "exit_code": 0}]),
            ("nonboolean stage passed", "stages", [{"passed": 1, "exit_code": 0}]),
            ("stage missing exit code", "stages", [{"passed": True}]),
            ("stage nonzero exit code", "stages", [{"passed": True, "exit_code": 1}]),
            ("stage noninteger exit code", "stages", [{"passed": True, "exit_code": False}]),
            ("stage string exit code", "stages", [{"passed": True, "exit_code": "0"}]),
        ]
        for label, field, value in cases:
            with self.subTest(case=label):
                rules = manifest()
                evidence = build.ROOT / rules["integration_evidence"][0]["path"]
                proof = json.loads(evidence.read_text())
                if value is None:
                    proof.pop(field)
                else:
                    proof[field] = value
                evidence.write_text(json.dumps(proof), encoding="utf-8")
                rules["integration_evidence"][0]["sha256"] = build.digest(evidence.read_bytes())
                with self.assertRaisesRegex(build.BuildError, "Qualification proof"):
                    self.make(rules)
        for proof in ([], {}, None):
            with self.subTest(incomplete_proof=proof):
                rules = manifest()
                evidence = build.ROOT / rules["integration_evidence"][0]["path"]
                evidence.write_text(json.dumps(proof), encoding="utf-8")
                rules["integration_evidence"][0]["sha256"] = build.digest(evidence.read_bytes())
                with self.assertRaisesRegex(build.BuildError, "Qualification proof"):
                    self.make(rules)
        rules = manifest()
        evidence = build.ROOT / rules["integration_evidence"][0]["path"]
        evidence.unlink()
        with self.assertRaisesRegex(build.BuildError, "JSON file inside this repository"):
            self.make(rules)

    def test_code_window_limits_and_missing_or_external_symbol_fail_closed(self):
        for payload in (b"", b"\xff" * (0x6000 + 1)):
            with self.assertRaises(build.BuildError):
                self.make(payload=payload)
        for symbols in ({}, {"entry": 0x16FFF}, {"entry": 0x17005}):
            with self.subTest(symbols=symbols), self.assertRaises(build.BuildError):
                build.apply_image(STOCK, BASELINE, manifest(), "usage", b"\x00\xbf\x70\x47", symbols)

    def test_thumb_encoding_matches_published_branch_and_rejects_truncation(self):
        self.assertEqual(build.thumb_branch(0x52B2, 0x17001, True), bytes.fromhex("11f0a5fe"))
        self.assertEqual(build.thumb_branch(0x1000, 0x1005, False), bytes.fromhex("00f000b8"))
        for source, target in ((0x1001, 0x2000), (0, 0x2000000), (0x2000000, 0)):
            with self.assertRaises(build.BuildError):
                build.thumb_branch(source, target, True)

    def test_elf_extraction_rejects_ram_initializers_overflows_and_wrong_architecture(self):
        payload, symbols = build.elf_payload(elf_fixture())
        self.assertEqual(payload, b"\x00\xbf\x70\x47")
        self.assertEqual(symbols["entry"], 0x17001)
        invalid = [elf_fixture(flags=3), elf_fixture(kind=8), elf_fixture(address=0x1CFFE),
                   elf_fixture(address=0x20000000), b"not ELF"]
        damaged = bytearray(elf_fixture()); struct.pack_into("<H", damaged, 18, 3); invalid.append(bytes(damaged))
        for index, data in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(build.BuildError):
                build.elf_payload(data)

    def test_usb_archive_is_reproducible_correctly_nested_and_hashed(self):
        image, _ = self.make()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = build.write_assets(output, "usage", image, {"hardware_validated": False})
            archive = next(item for item in first if item.suffix == ".zip")
            original_zip = archive.read_bytes()
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(package.namelist(), ["RCFW/GVK1EH_B002FFv.06.10.bin"])
                self.assertEqual(package.read(package.namelist()[0]), image)
            second = build.write_assets(output, "usage", image, {"hardware_validated": False})
            self.assertEqual(archive.read_bytes(), original_zip)
            details = json.loads((output / "manifest.json").read_text())
            self.assertFalse(details["hardware_validated"])
            for asset in details["assets"]:
                self.assertEqual(asset["sha256"], hashlib.sha256((output / asset["name"]).read_bytes()).hexdigest())
            with self.assertRaises(build.BuildError):
                build.write_assets(output, "usage", b"different", {})


if __name__ == "__main__":
    unittest.main()
