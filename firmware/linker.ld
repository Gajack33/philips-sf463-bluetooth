/* Existing image is 0x1d000 bytes. Added code uses only verified erased flash. */
MEMORY { PATCH (rx) : ORIGIN = 0x17000, LENGTH = 0x6000 }
SECTIONS
{
  .text : ALIGN(4) { *(.text .text.*) } > PATCH
  .rodata : ALIGN(4) { *(.rodata .rodata.*) } > PATCH
  .ARM.exidx : ALIGN(4) { *(.ARM.exidx*) } > PATCH
  .data : { *(.data .data.*) } > PATCH
  .bss : { *(.bss .bss.* COMMON) } > PATCH
  ASSERT(SIZEOF(.data) == 0, "Patch must not need a RAM data initializer")
  ASSERT(SIZEOF(.bss) == 0, "Patch RAM must be an explicitly reviewed absolute claim")
  ASSERT(. <= 0x1d000, "Patch exceeds the original image")
  /DISCARD/ : { *(.comment .note* .llvm_addrsig) }
}
