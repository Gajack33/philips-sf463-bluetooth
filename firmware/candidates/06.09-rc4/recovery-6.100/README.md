# 6.100 - private recovery contingency

Published 06.07 code and data, with only its 20-byte Software Revision and original CRC changed. The ZIP contains one file under `RCFW/`.

**Offline only. No installation approval; not deployed or flashed.** The actual Philips Java comparators establish `6.099 < 6.100 == 06.10 < 06.11`. Installing this recovery would consume the numeric version reserved for usage 06.10. Equality is rejected; an unchanged 06.10 filename could not replace it.

See `verification.json`: 9 recovery checks and 6 existing baseline checks. These checks do not qualify BLE timing, OTA recovery or long idle on hardware. This preserves 06.07 diagnostics and limitations, including its duplicate color mapping. A working native updater connection and a measured lower installed revision would still be necessary before any separately approved installation.
