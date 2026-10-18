# Offline firmware requirements

The modified application targets only **YKF463-001 / SF463**, factory image
`GVK1EH_B002FFv.06.05.bin` (118,784 bytes). The published, hardware-tested
06.07 remains an immutable comparison input. The uninstalled 06.08 is not used.

## Build and delivery boundaries

- Python 3.10+ and its standard library implement image/ELF/ZIP parsing and integrity checks.
- Compile with Clang/LLD for Cortex-M3, Thumb, soft-float, freestanding C11; the scoped local toolchain is official **Zig 0.14.1** (`zig cc`). No tool is installed by the builder.
- Tests of the existing 06.07 use the exact development packages in `requirements-analysis.txt`: Capstone 5.0.7, Unicorn 2.1.4, Keystone Engine 0.9.2. They are analysis dependencies, never remote/TV runtime dependencies.
- Newly linked code occupies only factory-erased flash `0x17000..0x1D000`; initialized data and BSS are forbidden. Any RAM ownership must be explicit in the adapter/integration evidence.
- Every native-code hook requires exact factory bytes and an explicit category-specific range. All bytes outside hooks, added code, software revision and CRC remain identical to stock. The header/vector prefix `0x0002..0x0100` is additionally protected.
- `firmware/hooks.json` is the integration contract. Schema 1 uses `hooks`, `allowed_ranges`, optional `protected_ranges`, `integration_qualified`, and hashed `integration_evidence` JSON records. A hook has `name`, `offset`, `expected_hex`, `category`, `kind`, optional `variants`, and either `replacement_hex` or `symbol`/`link`/optional `pad_hex`.
- Categories are `front`, `hid`, `diagnostic`, `uart`, `audio`, and `ota`. Naming a category grants no permission by itself: its allowed byte window must be explicit. UART, audio and OTA changes require their own qualified evidence.
- `diagnostic` is embedded version **06.09** and explicitly hooks Hardware Revision. `usage` is **06.10** and restores the original callback. Versions are local experimental revisions, never official Philips releases.
- `--check` compiles/audits into an external output directory, writes ELF/map/check evidence, and never writes a firmware `.bin` or USB ZIP. Normal output is refused unless integration qualification is true and every referenced evidence hash matches.
- Candidate assets are deterministic: image, `RCFW/<image>` USB ZIP with fixed ZIP metadata, manifest and SHA256SUMS. Each manifest states `hardware_validated: false`; compile/emulation success cannot change that fact.
- No network, TV control, automatic firmware installation, credentials, GitHub publication or production release belongs to this build pipeline.

```text
python -m unittest discover -s firmware/tests -p "test_image_build.py" -v
python firmware/build.py --variant usage --compiler /path/to/zig --check --out /outside/repository/usage
python firmware/build.py --variant diagnostic --compiler /path/to/clang --check --out /outside/repository/diagnostic
```

The compiler identity, command, source hashes, hook-manifest hash, resulting image
hash and symbols are recorded. Image/ZIP bytes are reproducible; provenance
paths and compiler identity in the JSON intentionally describe the actual build.

## Acceptance and remaining hardware work

Builder tests exercise real immutable input bytes, corrupted inputs, stale evidence,
expected-instruction mismatch, category/range errors, overlap, size limits,
Thumb branch encoding, ELF RAM-section rejection, CRC/revision preservation,
and deterministic USB packaging. Adapter/core tests separately qualify behavior
and instruction-level integration. No builder fixture is a usable firmware.

Candidate hardware validation must separately check both faces, short/held keys,
release delivery, reconnect bursts, voice, covered-IR wake, long idle, power usage,
and recovery limitations. Retain native battery/update thresholds and power policy.
The tested 06.07 result covers wake and one first press after 60 seconds without a
diagnostic reader; it does not prove overnight standby or automatic recovery.
