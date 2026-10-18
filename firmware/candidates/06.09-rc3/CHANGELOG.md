# 6.097 · 2026-10-18

- Defer bounded initialization to useful native lifecycle events.
- Protect an in-flight native report before reusing its queue storage.
- Fix physical Blue scan 1B from Yellow 006C to Blue 006B; other 44 rows unchanged.
- Add versioned latest-refusal scope and native-quiescence reason 11.

Validation:155 offline checks with LLVM 18/19; deterministic BIN/USB builds.
Hardware acceptance, actual memory margin and long standby remain pending.
