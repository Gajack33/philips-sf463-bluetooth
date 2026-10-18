# 6.098 · 06.07 code recovery

Contingency for the 6.097 experiment. **Not installed or authorized at preparation time.**
It requires a working native Bluetooth update link; recovery is not guaranteed.

Only Software Revision and CRC differ from published 06.07: 7 bytes in total.
Its diagnostics retain the 06.07 format, not the 6.097 decoder schema.
The old Blue/Yellow duplicate is retained. 15 narrow checks pass; these are
separate from the 155 reliability checks.

Recreate from published 06.07 by writing the 20-byte ASCII field
`GVK1EH_B002FFv.6.098` at `0x16E0`, then CRC16-CCITT (`crc_hqx(image[4:],0)`)
little-endian at bytes 0..1. No other byte may change.

[USB archive](SF463-6.098-recovery-USB.zip) · [Checksums](SHA256SUMS) · [Validation](verification.json)
