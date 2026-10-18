"""Build an offline, unflashed candidate from the verified factory image.

This bypasses one voice-only gate. It does not disable the separate IR MCU,
prove wake from deep standby, or make this image safe to install.
"""
from pathlib import Path
import binascii
import hashlib
import json
import struct

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'originals/ro/BTRC_FW/GVK1EH_B002FFv.06.05.bin'
EXPECTED_SHA = '6b97d87fd4923eb64a0e5f5efad1561900ed394ff3a7db97b3081cf5e316f040'
DEST = ROOT / 'candidates/usb/GVK1EH_B002FFv.06.06.bin'


def build():
    original = SOURCE.read_bytes()
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA:
        raise ValueError('Factory input hash mismatch')
    if len(original) != 118784 or original[0x1d28:0x1d2a] != b'\x05\xd1':
        raise ValueError('Unexpected image or instruction')
    if struct.unpack_from('<H', original)[0] != binascii.crc_hqx(original[4:], 0):
        raise ValueError('Factory CRC mismatch')
    candidate = bytearray(original)
    candidate[0x1d28:0x1d2a] = b'\x00\xbf'  # BNE 0x1d36 -> Thumb NOP.
    version = b'GVK1EH_B002FFv.06.05'
    if original.count(version) != 1 or original.find(version) != 0x16e0:
        raise ValueError('Unexpected software revision location')
    candidate[0x16e0:0x16e0 + len(version)] = b'GVK1EH_B002FFv.06.06'
    struct.pack_into('<H', candidate, 0, binascii.crc_hqx(candidate[4:], 0))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.read_bytes() != candidate:
        raise FileExistsError('Refusing to replace a different candidate')
    DEST.write_bytes(candidate)
    report = {
        'status': 'offline experimental candidate; NOT FLASHED',
        'source_sha256': EXPECTED_SHA,
        'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
        'size': len(candidate),
        'patch': {'offset': '0x1d28', 'before': '05d1', 'after': '00bf',
                  'meaning': 'Bypass the voice-only consumer-HID gate; retain readiness and pairing checks'},
        'crc16': f'{struct.unpack_from("<H", candidate)[0]:04x}',
        'software_revision': {'offset': '0x16e0', 'before': version.decode(),
                              'after': 'GVK1EH_B002FFv.06.06',
                              'meaning': 'Experimental local revision, not an official Philips release'},
        'changed_offsets': [f'0x{i:x}' for i, (a, b) in enumerate(zip(original, candidate)) if a != b],
        'unchanged': ['image size', 'metadata version', 'vectors',
                      'UART control', 'rear keyboard', 'OTA code'],
        'unproven': ['front UART events on hardware', 'duplicate IR and BLE actions',
                     'TV deep-standby wake', 'bootloader acceptance', 'recovery or rollback'],
    }
    DEST.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
