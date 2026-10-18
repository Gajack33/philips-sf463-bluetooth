"""Decode captured 06.09 Hardware Revision pages locally; never opens Bluetooth.

Active firmware rotates pages 0/1/2 on offset-zero reads. Each page is 20 hex
characters. Capture each entire page (including partial ATT reads) before the
next offset-zero read. The three pages are separate samples, not one snapshot.
"""
import argparse
import json
import re
import struct

PREFIX = "GVK1EH_B002FFv."
VERSION = "06.09"
LIMITS = [
    "Heap minimum is the minimum sampled free value, not a continuous low-water mark.",
    "UART activity uses logical flag 6, not driver-open flag 5 or electrical power.",
    "Pages are captured separately; their values are not one atomic cross-page snapshot.",
    "Drop/retry values contain the low 16 bits; activity millisecond counters wrap at 32 bits.",
    "Clock accounting cannot reconstruct multiple unobserved native tick wraps during long idle.",
    "Activity indicators do not establish battery-life improvement.",
    "Last front index is a captured UART key index; physical button identity requires a matching press observation.",
]


def decode_pages(firmware_version: str, pages: list[str]) -> dict:
    """Validate the exact page schema before interpreting any field."""
    version = firmware_version.strip()
    if version.startswith(PREFIX):
        version = version[len(PREFIX):]
    if version != VERSION:
        raise ValueError("Only diagnostic firmware 06.09 uses this page schema; 06.07 and usage 06.10 do not")
    if len(pages) not in (1, 3):
        raise ValueError("Provide three active pages, or one/three all-zero inactive pages")
    decoded = []
    for page in pages:
        value = page.strip()
        if len(value) != 20 or re.fullmatch(r"[0-9A-Fa-f]{20}", value) is None:
            raise ValueError("Every page must contain exactly 20 hexadecimal characters")
        raw = bytes.fromhex(value)
        if raw[0] not in (0, 1, 2) or raw[1] not in (0, 1):
            raise ValueError("Invalid page ID or active-state flag")
        decoded.append(raw)
    active_values = {page[1] for page in decoded}
    if len(active_values) != 1:
        raise ValueError("Pages disagree about adapter activation; capture a fresh set")
    report = {"schema": 1, "firmware_version": VERSION, "improvements_active": bool(decoded[0][1]),
              "memory": None, "events": None, "activity": None, "link": None,
              "limitations": list(LIMITS)}
    if not decoded[0][1]:
        if any(page != bytes(10) for page in decoded):
            raise ValueError("Inactive 06.09 firmware emits only an all-zero page 0")
        report["status"] = "fallback_inactive"
        report["message"] = "Native fallback is active; reliability extensions are not initialized."
        return report
    if len(decoded) != 3 or {page[0] for page in decoded} != {0, 1, 2}:
        raise ValueError("Active diagnostics require exactly one page each with IDs 0, 1 and 2")
    by_id = {page[0]: page for page in decoded}
    minimum, source_dropped, tx_dropped, retries = struct.unpack_from("<HHHH", by_id[0], 2)
    connected, uart_active = struct.unpack_from("<II", by_id[1], 2)
    uart_inactive = struct.unpack_from("<I", by_id[2], 2)[0]
    front_index, repair_mask, role, packed = by_id[2][6:]
    pending, verified, index_valid = packed & 0x1F, bool(packed & 0x80), bool(packed & 0x40)
    if pending > 16 or repair_mask & ~3 or packed & 0x20 or (index_valid and front_index > 44):
        raise ValueError("Invalid queue, repair, reserved bit or front index for the 06.09 schema")
    report.update({
        "status": "active",
        "memory": {"minimum_sampled_free_bytes": minimum},
        "events": {"source_dropped_low16": source_dropped, "tx_dropped_low16": tx_dropped,
                   "retries_low16": retries, "tx_pending": pending, "repair_mask": repair_mask,
                   "last_front_index": front_index if index_valid else None},
        "activity": {"connected_ms": connected, "uart_logical_active_ms": uart_active,
                     "uart_logical_inactive_ms": uart_inactive},
        "link": {"role_state": role, "identity_verified": verified},
    })
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-version", required=True,
                        help="Explicit embedded firmware version, e.g. 06.09 (not the USB filename)")
    parser.add_argument("pages", nargs="+", help="Already captured 20-character hexadecimal pages")
    args = parser.parse_args(argv)
    try:
        report = decode_pages(args.firmware_version, args.pages)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
