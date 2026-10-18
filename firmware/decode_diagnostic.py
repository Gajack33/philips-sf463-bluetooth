"""Decode captured 06.09 / 6.095 / 6.097 diagnostic pages; never opens Bluetooth.

Active firmware rotates pages 0/1/2 on offset-zero reads. Each page is 20 hex
characters. Capture each entire page (including partial ATT reads) before the
next offset-zero read. The three pages are separate samples, not one snapshot.
Inactive page 0 is a boot-failure record in06.09/6.095. Version6.097 records
the latest admission refusal, with flag0x10 distinguishing deferred attempts.
GATT reads do not change this record. Legacy zeroes are not measurements.
"""
import argparse
import json
import re
import struct

PREFIX = "GVK1EH_B002FFv."
VERSION = "06.09"
VERSIONS = (VERSION, "6.095", "6.097")
FALLBACK_REASONS = {
    0: "unknown",
    1: "hid_semaphore_missing",
    2: "bond_count_not_one",
    3: "bond_identity_rpc_failed",
    4: "zero_bond_identity",
    5: "insufficient_total_free",
    6: "insufficient_largest_block",
    7: "allocation_failed",
    8: "insufficient_post_allocation_free",
    9: "hid_queue_busy",
    10: "app_mailbox_busy",
    11: "native_transmission_not_quiescent",
}
LIMITS = [
    "Heap minimum is the minimum sampled free value, not a continuous low-water mark.",
    "UART activity uses logical flag 6, not driver-open flag 5 or electrical power.",
    "Pages are captured separately; their values are not one atomic cross-page snapshot.",
    "Drop/retry values contain the low 16 bits; activity millisecond counters wrap at 32 bits.",
    "Clock accounting cannot reconstruct multiple unobserved native tick wraps during long idle.",
    "Activity indicators do not establish battery-life improvement.",
    "Last front index is a captured UART key index; physical button identity requires a matching press observation.",
]


def _decode_inactive(raw: bytes, version: str) -> dict:
    """Decode a frozen fallback record, keeping allocation phases distinct."""
    if raw[0] != 0:
        raise ValueError("Inactive diagnostics require page 0")
    legacy = raw == bytes(10)
    reason, bond_raw = raw[2:4]
    free_raw, largest_raw = struct.unpack_from("<HH", raw, 4)
    flags, role = raw[8:]
    allowed_flags = 0x1F if version == "6.097" else 0x0F
    if reason not in FALLBACK_REASONS or flags & ~allowed_flags:
        raise ValueError("Invalid inactive fallback reason or reserved flags")
    if reason == 11 and version != "6.097":
        raise ValueError("Fallback reason 11 requires diagnostic firmware 6.097")
    if reason == 0 and flags & 0x10:
        raise ValueError("Unknown fallback provenance cannot claim a deferred admission refusal")
    bond = None if legacy or bond_raw == 0xFF else bond_raw
    free = None if legacy or free_raw == 0xFFFF else free_raw
    largest = None if legacy or largest_raw == 0xFFFF else largest_raw
    if not legacy:
        if free is not None and largest is not None and largest > free:
            raise ValueError("Inactive largest block contradicts total free bytes")
        if reason <= 4 and (free is not None or largest is not None):
            raise ValueError("Inactive fallback reason requires unknown heap statistics")
        if reason in (0, 1) and bond is not None:
            raise ValueError("Inactive fallback reason requires an unknown bond count")
        if reason == 1 and flags & 1:
            raise ValueError("Missing-semaphore reason contradicts the semaphore flag")
        if reason >= 2 and not flags & 1:
            raise ValueError("Inactive fallback reason contradicts an absent semaphore")
        if reason == 2 and bond == 1:
            raise ValueError("Bond-count reason contradicts the captured bond count")
        if reason >= 3 and reason != 11 and bond != 1:
            raise ValueError("Inactive fallback reason requires exactly one bond")
        if reason == 11:
            if (free is None) != (largest is None):
                raise ValueError("Quiescence refusal requires both heap samples or neither")
            if free is None and bond is not None:
                raise ValueError("Pre-query quiescence refusal requires an unknown bond count")
            if free is not None and (bond != 1 or free < 768):
                raise ValueError("Final quiescence refusal requires a valid post-allocation sample")
        if 5 <= reason <= 10:
            if free is None or largest is None:
                raise ValueError("Inactive allocation failure requires known heap statistics")
            if reason == 5 and free >= 1416:
                raise ValueError("Total-free reason contradicts pre-allocation free bytes")
            if reason in (6, 7) and free < 1416:
                raise ValueError("Inactive fallback reason contradicts pre-allocation free bytes")
            if reason == 6 and largest >= 640:
                raise ValueError("Largest-block reason contradicts pre-allocation block size")
            if reason == 7 and largest < 640:
                raise ValueError("Allocation-failed reason contradicts pre-allocation block size")
            if reason == 8 and free >= 768:
                raise ValueError("Post-allocation reason contradicts post-allocation free bytes")
            if reason in (9, 10) and free < 768:
                raise ValueError("Queue/mailbox reason contradicts post-allocation free bytes")
        if reason == 9 and not flags & 2:
            raise ValueError("HID-queue reason contradicts the queue-busy flag")
        if reason == 10 and (not flags & 0x0C or flags & 2):
            raise ValueError("APP-mailbox reason contradicts queue/mailbox flags")
    phase = ("pre_allocation" if reason in (5, 6, 7) else
             "post_allocation_before_release" if reason in (8, 9, 10) or (reason == 11 and free is not None)
             else "unknown")
    result = {
        "reason_code": reason,
        "reason": FALLBACK_REASONS[reason],
        "bond_count": bond,
        "heap": None if free is None and largest is None else {
            "free_bytes": free, "largest_free_block_bytes": largest, "sample_phase": phase},
        "flags": {"raw": None if legacy else flags,
                  "hid_semaphore_present": None if legacy else bool(flags & 1),
                  "hid_queue_busy": None if legacy else bool(flags & 2),
                  "app_front_pending": None if legacy else bool(flags & 4),
                  "app_rear_pending": None if legacy else bool(flags & 8)},
        "role_state": None if legacy else role,
        "legacy_all_zero": legacy,
    }
    if version == "6.097":
        result["snapshot_scope"] = ("unknown" if reason == 0 else
                                    "latest_deferred_admission_refusal" if flags & 0x10 else
                                    "latest_boot_admission_refusal")
        result["flags"]["deferred_admission"] = None if reason == 0 else bool(flags & 0x10)
    return result


def decode_pages(firmware_version: str, pages: list[str]) -> dict:
    """Validate the exact page schema before interpreting any field."""
    version = firmware_version.strip()
    if version.startswith(PREFIX):
        version = version[len(PREFIX):]
    if version not in VERSIONS:
        raise ValueError("Only diagnostic firmware 06.09, 6.095 and 6.097 use this page schema; 06.07 and usage 06.10 do not")
    if len(pages) not in (1, 3):
        raise ValueError("Provide three active pages, or one/three identical inactive page-0 snapshots")
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
    report = {"schema": 1, "firmware_version": version, "improvements_active": bool(decoded[0][1]),
              "memory": None, "events": None, "activity": None, "link": None,
              "limitations": list(LIMITS)}
    if not decoded[0][1]:
        if any(page[0] != 0 for page in decoded):
            raise ValueError("Inactive diagnostics require page 0")
        if any(page != decoded[0] for page in decoded):
            raise ValueError("Inactive snapshots differ; provide one snapshot or capture a fresh set")
        report["status"] = "fallback_inactive"
        report["message"] = "Native fallback is active; reliability extensions are not initialized."
        report["fallback"] = _decode_inactive(decoded[0], version)
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
        raise ValueError("Invalid queue, repair, reserved bit or front index for the diagnostic schema")
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
                        help="Explicit embedded firmware version: 06.09, 6.095 or 6.097 (not the USB filename)")
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
