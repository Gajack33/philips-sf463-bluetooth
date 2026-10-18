"""Emulate only IAR's RAM initializer from the public image, never hardware.

No peripheral or ROM implementation is supplied. Completion is accepted only if
the initializer returns to the sentinel within the instruction/time allowance.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'python-tools'))
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC

source=ROOT/'originals/ro/BTRC_FW/GVK1EH_B002FFv.06.05.bin'
firmware=source.read_bytes()
emu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
emu.mem_map(0,0x20000);emu.mem_write(0,firmware)
emu.mem_map(0x20000000,0x8000)
sentinel=0x30000000
emu.mem_map(sentinel,0x1000)
emu.reg_write(UC_ARM_REG_SP,0x20004300)
emu.reg_write(UC_ARM_REG_LR,sentinel|1)
emu.emu_start(0x15789,sentinel,timeout=5_000_000,count=2_000_000)
pc=emu.reg_read(UC_ARM_REG_PC)
if pc!=sentinel:raise RuntimeError(f'Initializer not completed, pc={pc:#x}')
ram=bytes(emu.mem_read(0x20000000,0x5000))
(ROOT/'ram-init-emulated.bin').write_bytes(ram)
meta={'firmware_sha256':hashlib.sha256(firmware).hexdigest(),
    'scope':'Only the IAR RAM-initialization routine, no remote hardware execution',
    'entry':'0x00015788','returned_to_sentinel':True,
    'ram_sha256':hashlib.sha256(ram).hexdigest(),
    'limits':'Does not emulate GPIO, UART, BLE, ROM, interrupts or TV wake.'}
(ROOT/'ram-init-emulated.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(meta),flush=True)
for address in [0x20000928+0x178,0x20000928+0x180,0x20000928+0x184,0x20000928+0x188]:
    print('Initialized callback/config',hex(address),hex(struct.unpack_from('<I',ram,address-0x20000000)[0]))
