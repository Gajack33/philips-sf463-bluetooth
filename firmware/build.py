"""Reproducible, fail-closed SF463 offline image builder. Never flashes hardware.

--check compiles and audits the integration without writing a firmware image.
Image/USB output additionally requires an explicitly qualified hook manifest.
The published 06.07 and factory images are read-only inputs, never overwritten.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STOCK_SHA = "6b97d87fd4923eb64a0e5f5efad1561900ed394ff3a7db97b3081cf5e316f040"
BASELINE_SHA = "35514fcd675876d4e016e23f389c58aab447db1bda1703adecef50834bda4a40"
IMAGE_SIZE = 118784
PATCH_START, PATCH_END = 0x17000, 0x1D000
VERSION_OFFSET = 0x16E0
VERSIONS = {"diagnostic": "6.095", "usage": "06.10"}
CATEGORIES = {"front", "hid", "diagnostic", "uart", "audio", "ota"}
QUALIFICATION_FIELDS = {"integration_qualified", "integration_evidence", "integration_sources",
                        "integration_hook_sha256", "qualification_note"}


class BuildError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def number(value) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def crc(image: bytes) -> int:
    return binascii.crc_hqx(image[4:], 0)


def ranges_cover(offset: int, length: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= offset and offset + length <= end for start, end in ranges)


def validate_inputs(stock: bytes, baseline: bytes) -> None:
    for label, image, expected in (("factory", stock, STOCK_SHA),
                                   ("06.07 baseline", baseline, BASELINE_SHA)):
        if len(image) != IMAGE_SIZE or digest(image) != expected:
            raise BuildError(f"Unexpected {label} size or SHA-256")
        if struct.unpack_from("<H", image)[0] != crc(image):
            raise BuildError(f"Invalid {label} CRC")
        if struct.unpack_from("<H", image, 6)[0] * 4 != len(image):
            raise BuildError(f"Invalid {label} declared image length")
    if stock[VERSION_OFFSET:VERSION_OFFSET + 20] != b"GVK1EH_B002FFv.06.05":
        raise BuildError("Unexpected factory software revision")
    allowed = [(0, 2), (VERSION_OFFSET, VERSION_OFFSET + 20),
               (0x1D28, 0x1D2A), (0x52B2, 0x52B6), (PATCH_START, PATCH_START + 302)]
    for index, (before, after) in enumerate(zip(stock, baseline)):
        if before != after and not ranges_cover(index, 1, allowed):
            raise BuildError(f"Unexpected published baseline difference at {index:#x}")
    if any(value != 255 for value in stock[PATCH_START:PATCH_END]):
        raise BuildError("Patch flash is not erased in the factory image")


def thumb_branch(source: int, target: int, link: bool) -> bytes:
    """Encode Thumb-2 BL/B.W, with PC+4 and signed 25-bit displacement."""
    target &= ~1  # Function symbols carry the Thumb bit.
    delta = target - source - 4
    if source & 1 or delta & 1 or not -(1 << 24) <= delta < (1 << 24):
        raise BuildError("Unaligned or out-of-range Thumb branch")
    encoded = delta & ((1 << 25) - 1)
    sign, i1, i2 = (encoded >> 24) & 1, (encoded >> 23) & 1, (encoded >> 22) & 1
    j1, j2 = 1 ^ i1 ^ sign, 1 ^ i2 ^ sign
    first = 0xF000 | sign << 10 | (encoded >> 12) & 0x3FF
    second = (0xD000 if link else 0x9000) | j1 << 13 | j2 << 11 | (encoded >> 1) & 0x7FF
    return struct.pack("<HH", first, second)


def elf_payload(data: bytes) -> tuple[bytes, dict[str, int]]:
    """Read ELF32 ARM allocated sections, rejecting hidden RAM/data segments."""
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise BuildError("Compiler did not produce little-endian ELF32")
    if struct.unpack_from("<HH", data, 16) != (2, 40):
        raise BuildError("Expected an ARM executable, not a relocatable object")
    section_offset = struct.unpack_from("<I", data, 32)[0]
    entry_size, count = struct.unpack_from("<HH", data, 46)
    if entry_size != 40 or not count or section_offset + count * entry_size > len(data):
        raise BuildError("Malformed ELF section table")
    sections = [struct.unpack_from("<10I", data, section_offset + i * 40) for i in range(count)]
    image = bytearray(b"\xff" * (PATCH_END - PATCH_START))
    claimed: list[tuple[int, int]] = []
    highest = PATCH_START
    symbols: dict[str, int] = {}
    for section in sections:
        _, kind, flags, address, offset, size, link, _, _, entsize = section
        if flags & 2 and size:
            if flags & 1 or kind == 8:
                raise BuildError("Allocated writable/NOBITS sections require forbidden RAM initialization")
            if address < PATCH_START or address + size > PATCH_END or offset + size > len(data):
                raise BuildError("Allocated ELF section lies outside the reviewed flash window")
            if any(address < end and start < address + size for start, end in claimed):
                raise BuildError("Overlapping allocated ELF sections")
            claimed.append((address, address + size))
            image[address - PATCH_START:address - PATCH_START + size] = data[offset:offset + size]
            highest = max(highest, address + size)
        if kind == 2:  # SHT_SYMTAB
            if link >= count or entsize != 16 or offset + size > len(data) or size % 16:
                raise BuildError("Malformed ELF symbol table")
            string_section = sections[link]
            strings = data[string_section[4]:string_section[4] + string_section[5]]
            for start in range(offset, offset + size, 16):
                name, value, _, _, _, defined = struct.unpack_from("<IIIBBH", data, start)
                if name >= len(strings):
                    raise BuildError("Invalid ELF symbol name")
                end = strings.find(b"\0", name)
                if end < 0:
                    raise BuildError("Unterminated ELF symbol name")
                if defined and name:
                    symbols[strings[name:end].decode("ascii")] = value
    if not claimed or highest == PATCH_START:
        raise BuildError("Compiler emitted no patch code")
    return bytes(image[:highest - PATCH_START]), symbols


def variant_hooks(manifest: dict, variant: str) -> list[dict]:
    if manifest.get("schema") != 1 or variant not in VERSIONS:
        raise BuildError("Unknown hook schema or build variant")
    return [hook for hook in manifest.get("hooks", [])
            if variant in hook.get("variants", [hook["variant"]] if "variant" in hook else list(VERSIONS))]


def source_files() -> list[Path]:
    """Production inputs only; host test programs never enter the remote image."""
    files = [ROOT / "firmware/build.py", ROOT / "firmware/linker.ld"]
    for directory in (ROOT / "firmware", ROOT / "firmware/core"):
        files.extend(path for path in directory.iterdir() if path.is_file()
                     and path.suffix in {".c", ".h", ".S"} and not path.name.startswith("test_"))
    return sorted(files)


def source_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path.read_bytes())
            for path in source_files()}


def hook_digest(manifest: dict) -> str:
    material = {key: value for key, value in manifest.items() if key not in QUALIFICATION_FIELDS}
    return digest(json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def validate_evidence(manifest: dict, variant: str | None = None, image_sha256: str | None = None) -> None:
    if manifest.get("integration_sources") != source_hashes():
        raise BuildError("Qualification source binding mismatch: production sources changed")
    if manifest.get("integration_hook_sha256") != hook_digest(manifest):
        raise BuildError("Qualification hook binding mismatch: hook manifest changed")
    records = manifest.get("integration_evidence", [])
    if not records:
        raise BuildError("Qualified integration requires hashed evidence files")
    image_matches = False
    for record in records:
        path = (ROOT / record["path"]).resolve()
        if ROOT not in path.parents or path.suffix != ".json" or not path.is_file():
            raise BuildError("Integration evidence must be a JSON file inside this repository")
        data = path.read_bytes()
        if digest(data) != record["sha256"]:
            raise BuildError(f"Integration evidence hash mismatch: {record['path']}")
        proof = json.loads(data)
        if not isinstance(proof, dict) or proof.get("passed") is not True:
            raise BuildError("Qualification proof must report passed=true")
        if proof.get("inputs_unchanged") is not True:
            raise BuildError("Qualification proof must report unchanged verification inputs")
        if proof.get("sources") != manifest["integration_sources"]:
            raise BuildError("Qualification proof source binding mismatch")
        if proof.get("integration_hook_sha256") != manifest["integration_hook_sha256"]:
            raise BuildError("Qualification proof hook binding mismatch")
        stages = proof.get("stages")
        if (not isinstance(stages, list) or not stages
                or any(not isinstance(stage, dict) or stage.get("passed") is not True
                       or type(stage.get("exit_code")) is not int or stage["exit_code"] != 0
                       for stage in stages)):
            raise BuildError("Qualification proof contains failing or incomplete stages")
        if variant is not None and proof.get("variant_images", {}).get(variant) == image_sha256:
            image_matches = True
    if variant is not None and not image_matches:
        raise BuildError("Qualification image binding mismatch: no evidence matches this variant's exact image")


def apply_image(stock: bytes, baseline: bytes, manifest: dict, variant: str,
                payload: bytes, symbols: dict[str, int], *, require_qualified=True) -> tuple[bytes, list[dict]]:
    validate_inputs(stock, baseline)
    hooks = variant_hooks(manifest, variant)
    if require_qualified and manifest.get("integration_qualified") is not True:
        raise BuildError("Integration is not qualified: firmware/USB image output is disabled")
    if require_qualified:
        validate_evidence(manifest)
    if not hooks:
        raise BuildError("No hooks configured for this variant")
    if not payload or len(payload) > PATCH_END - PATCH_START:
        raise BuildError("Patch code is empty or exceeds the erased flash window")
    ranges = []
    for item in manifest.get("allowed_ranges", []):
        start, end = number(item["start"]), number(item["end"])
        category = item["category"]
        if category not in CATEGORIES or start < 0x100 or end > PATCH_START or start >= end:
            raise BuildError("Invalid hook allowlist range")
        ranges.append((start, end, category))
    protected = [(number(item["start"]), number(item["end"]))
                 for item in manifest.get("protected_ranges", [])]
    image = bytearray(stock)
    claimed = [(0, 2), (VERSION_OFFSET, VERSION_OFFSET + 20),
               (PATCH_START, PATCH_START + len(payload))]
    applied = []
    for hook in hooks:
        offset = number(hook["offset"])
        before = bytes.fromhex(hook["expected_hex"])
        if not before or stock[offset:offset + len(before)] != before:
            raise BuildError(f"Expected instruction mismatch for {hook.get('name', offset)}")
        if hook["category"] not in CATEGORIES or not any(
                start <= offset and offset + len(before) <= end and category == hook["category"]
                for start, end, category in ranges):
            raise BuildError(f"Hook {hook.get('name', offset)} is outside its category allowlist")
        if any(offset < end and start < offset + len(before) for start, end in claimed):
            raise BuildError("Overlapping hook, protected metadata, or added code")
        if any(offset < end and start < offset + len(before) for start, end in protected):
            raise BuildError("Hook overlaps a protected vector or peripheral range")
        if hook["kind"] == "bytes":
            after = bytes.fromhex(hook["replacement_hex"])
        elif hook["kind"] == "branch":
            symbol = hook["symbol"]
            if symbol not in symbols or not PATCH_START <= (symbols[symbol] & ~1) < PATCH_START + len(payload):
                raise BuildError(f"Hook symbol {symbol} is missing or outside the linked code")
            after = thumb_branch(offset, symbols[symbol], hook.get("link", True))
            after += bytes.fromhex(hook.get("pad_hex", ""))
        else:
            raise BuildError("Unknown hook kind")
        if len(after) != len(before):
            raise BuildError("A hook may not change instruction-window size")
        image[offset:offset + len(after)] = after
        claimed.append((offset, offset + len(after)))
        applied.append({"name": hook["name"], "offset": hex(offset),
                        "before": before.hex(), "after": after.hex(), "category": hook["category"]})
    if image[0x1D28:0x1D2A] != b"\x00\xbf":
        raise BuildError("The verified front-key gate patch is missing")
    if variant == "usage" and (image[0x5250:0x5254] != stock[0x5250:0x5254]
                               or image[0x52B2:0x52B6] != stock[0x52B2:0x52B6]):
        raise BuildError("Usage build must preserve the factory Hardware Revision callback")
    if variant == "diagnostic" and image[0x5250:0x5254] == stock[0x5250:0x5254]:
        raise BuildError("Diagnostic build must explicitly install its reviewed callback")
    image[PATCH_START:PATCH_START + len(payload)] = payload
    image[VERSION_OFFSET:VERSION_OFFSET + 20] = f"GVK1EH_B002FFv.{VERSIONS[variant]}".encode("ascii")
    struct.pack_into("<H", image, 0, crc(image))
    if image[2:0x100] != stock[2:0x100] or len(image) != len(stock):
        raise BuildError("Protected header/vector prefix or image size changed")
    for index, (before, after) in enumerate(zip(stock, image)):
        if before != after and not ranges_cover(index, 1, claimed):
            raise BuildError(f"Unapproved change at {index:#x}")
    if require_qualified:
        validate_evidence(manifest, variant, digest(image))
    return bytes(image), applied


def compiler_command(path: str | None) -> list[str]:
    executable = path or os.environ.get("SF463_COMPILER") or shutil.which("clang")
    if not executable:
        raise BuildError("Pass --compiler <clang or zig executable>; no compiler is installed automatically")
    return [executable, "cc"] if Path(executable).stem.lower() == "zig" else [executable]


def compile_patch(manifest: dict, variant: str, compiler: str | None, output: Path) -> tuple[bytes, dict, list[str]]:
    sources = [ROOT / "firmware" / "adapter.c",
               *sorted((ROOT / "firmware").glob("*.S")),
               *sorted(path for path in (ROOT / "firmware" / "core").glob("*.c")
                       if not path.name.startswith("test_")),
               *sorted((ROOT / "firmware" / "core").glob("*.S"))]
    if len(sources) < 2 or any(not source.is_file() for source in sources):
        raise BuildError("Adapter and core sources must exist before a build")
    command = compiler_command(compiler)
    version = subprocess.run(command + ["--version"], check=True, capture_output=True, text=True).stdout.strip()
    zig = len(command) == 2
    flags = (["-target", "thumb-freestanding-eabi"] if zig else ["--target=arm-none-eabi", "-fuse-ld=lld"])
    flags += ["-mcpu=" + ("cortex_m3" if zig else "cortex-m3"), "-mthumb", "-mfloat-abi=soft", "-Oz", "-std=c11",
              "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
              "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections",
              "-Wall", "-Wextra", "-Werror", "-nostdlib", "-g" if zig else "-g0",
              f"-DRC_DIAGNOSTIC={int(variant == 'diagnostic')}",
              f"-I{ROOT / 'firmware' / 'core'}", "-Wl,--gc-sections", "-Wl,--build-id=none",
              f"-Wl,-T,{ROOT / 'firmware' / 'linker.ld'}"]
    if not zig:
        flags.append(f"-Wl,-Map,{output / 'patch.map'}")
    for hook in variant_hooks(manifest, variant):
        if hook.get("kind") == "branch":
            flags.append(f"-Wl,-u,{hook['symbol']}")
    elf = output / "patch.elf"
    invocation = command + flags + [str(source) for source in sources] + ["-o", str(elf)]
    subprocess.run(invocation, check=True, capture_output=True, text=True)
    payload, symbols = elf_payload(elf.read_bytes())
    if zig:
        # Zig's CC linker-argument parser does not support GNU -Map. Symbols
        # are extracted from its unstripped ELF rather than inventing a map.
        (output / "symbols.map").write_text("# ELF symbol addresses (not a linker allocation map)\n" +
            "".join(f"{address:08x} {name}\n" for name, address in sorted(symbols.items())), encoding="utf-8")
    return payload, symbols, [version, *invocation]


def write_new(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() != data:
        raise BuildError(f"Refusing to replace a different artifact: {path}")
    path.write_bytes(data)


def write_assets(output: Path, variant: str, image: bytes, report: dict) -> list[Path]:
    filename = f"GVK1EH_B002FFv.{VERSIONS[variant]}.bin"
    binary = output / filename
    archive = output / f"SF463-{VERSIONS[variant]}-{variant}-USB.zip"
    write_new(binary, image)
    # ZIP metadata is fixed, so repeated builds produce identical archives.
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as package:
        item = zipfile.ZipInfo(f"RCFW/{filename}", (1980, 1, 1, 0, 0, 0))
        item.external_attr = 0o100644 << 16
        package.writestr(item, image)
    write_new(archive, stream.getvalue())
    assets = [binary, archive]
    report["assets"] = [{"name": item.name, "size": item.stat().st_size,
                         "sha256": digest(item.read_bytes())} for item in assets]
    manifest = output / "manifest.json"
    write_new(manifest, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    assets.append(manifest)
    write_new(output / "SHA256SUMS", "".join(f"{digest(item.read_bytes())}  {item.name}\n"
                                             for item in assets).encode())
    return assets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler")
    parser.add_argument("--variant", choices=VERSIONS, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--hooks", type=Path, default=ROOT / "firmware" / "hooks.json")
    parser.add_argument("--check", action="store_true", help="Compile and audit only; never write .bin or USB ZIP")
    args = parser.parse_args(argv)
    try:
        stock = (ROOT / "firmware/original/GVK1EH_B002FFv.06.05.bin").read_bytes()
        baseline = (ROOT / "firmware/RCFW/GVK1EH_B002FFv.06.07.bin").read_bytes()
        validate_inputs(stock, baseline)
        manifest = json.loads(args.hooks.read_text(encoding="utf-8"))
        variant_hooks(manifest, args.variant)
        if not args.check and manifest.get("integration_qualified") is not True:
            raise BuildError("Integration is not qualified: use --check for offline analysis only")
        output = (args.out or ROOT.parent / "SF463-implementation" / args.variant).resolve()
        if output == ROOT or ROOT in output.parents:
            raise BuildError("Build output must be outside the repository and its published firmware")
        output.mkdir(parents=True, exist_ok=True)
        payload, symbols, compiler = compile_patch(manifest, args.variant, args.compiler, output)
        image, patches = apply_image(stock, baseline, manifest, args.variant, payload, symbols,
                                      require_qualified=not args.check)
        report = {"schema": 1, "variant": args.variant, "version": VERSIONS[args.variant],
                  "status": "offline-check-only" if args.check else "offline-candidate-not-flashed",
                  "hardware_validated": False, "baseline": {"factory_sha256": STOCK_SHA, "06.07_sha256": BASELINE_SHA},
                  "image_sha256": digest(image), "size": len(image), "crc16": f"{crc(image):04x}",
                  "added_code": {"start": hex(PATCH_START), "size": len(payload), "sha256": digest(payload)},
                  "patches": patches, "symbols": {name: hex(value) for name, value in sorted(symbols.items())},
                  "compiler": compiler[0], "command": compiler[1:],
                  "hook_manifest_sha256": digest(args.hooks.read_bytes()),
                  "integration_hook_sha256": hook_digest(manifest), "sources": source_hashes()}
        if args.check:
            (output / "check.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            write_assets(output, args.variant, image, report)
        print(json.dumps({key: report[key] for key in ("status", "variant", "version", "image_sha256", "hardware_validated")}))
        return 0
    except (BuildError, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"Build refused: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
