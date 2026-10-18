# Reliability and companion verification

## Current delivery — 6.099, offline only

**178/178 checks pass independently with LLVM 18 and 19**, with unchanged inputs
across all nine stages: 129 firmware tests, 16 C tests under ASan/UBSan,
22 Java tests and 11 baseline tests. Source commit `e375ddabab81a50985ccf4854fcdd20bff55065b`
is bound by `evidence/reliability-rc4-offline.json` and its LLVM 18 counterpart.
The deterministic BIN/USB package is in `firmware/candidates/06.09-rc4/`.
The normal-use image remains check-only. No 6.099 installation is authorized.
The working restored 6.098 remains on the remote.

| Requirement | Evidence |
| --- | --- |
| Safe native reader/APP ownership handoff | `test_complete_next_slot_is_private_before_publishing_index_including_wrap`, `test_magic_claim_during_native_rpc_preserves_shadow_and_skips_legacy_postlude`, `test_stack_handoff_preserves_real_last_report_during_admission_before_and_after_precheck` |
| No inherited Power replay or lost fresh action | `test_power_handoff_repeat_is_red_without_source_fence_and_green_with_it`, native release-only 41 and pending voice221 comparisons, rear-source release/refusal tests |
| Reliable pending cache after neutrals/expiry | `test_thumb_initial_neutrals_preserve_latest_fresh_fifo_state_for_both_reports`, `test_thumb_expiring_old_press_preserves_newer_valid_pending_press_dedupe`, two new ASan/UBSan host cases |
| Source overflow and actual key-up order | Refused/fragmented release and suspended-dispatch tests in `test_native_handoff.py` |
| Versioned reason12 without queries on read | `test_rear_source_refusal_*`, historical reason11 version rejection, actual compiled GATT refusal tests |
| Stack and register preservation | Native handoff/ABI tests and `evidence/stack-review-6099.json`; prefixes only, full ROM/RTOS headroom unqualified |

The separately prepared 6.100 recovery has 15 narrow checks and baseline code
only. If installed it consumes numeric 06.10; a later usage version must be newer.
No automatic flash, radio/power change or battery-life claim.

## Historical device trials and proofs

Scope: software implementation and offline integration; **not hardware qualification**.
The published 06.07 remains unchanged. The first 06.09 was installed with the
owner's explicit approval, but reports inactive fallback on the test remote.
The 6.095 (06.09 rc2) refusal-diagnostic transfer completed with owner authorization.
After a separately authorized host forget/re-pair, the TV again has PHLRC input
and six ATT reads completed with status 0. Actual 6.095 is confirmed; its frozen
snapshot is `00000200FFFFFFFF0101`: reason 2, bond count 0 at initial admission,
semaphore present, role 1, no heap sample or allocation. This does not prove why
inventory was zero. See `evidence/hardware-6095.json`.
**Historical 6.095 hold:** host re-pair restored its Bluetooth connection, but
its reliability core stayed inactive. That candidate remains on hold; 6.097 is a
new separately tested build requiring its own hardware acceptance.
The separately authorized 06.07 behavior recovery 6.096 was confirmed. After
the first attempt failed before any firmware write, host re-pair restored the link;
a second native attempt completed 3,712 blocks and an independent six-read ATT
sequence confirmed version 6.096 with status 0. Its 15 narrow offline checks are
separate from the 134 reliability tests. Both faces and the first press after an
unmeasured pause work with infrared covered according to the owner; exact
60-second and longer-idle checks remain unqualified; the passive window also
contains infrared, so Bluetooth-only first press is not independently established;
see `evidence/hardware-recovery-6096.json`.
06.08 is not a build input. Exact test IDs and hashes are in
`evidence/reliability-rc2-offline.json`; the complete command is `python firmware/verify.py`.

Historical 6.097 delivery: **155/155 checks pass with LLVM 18 and 19**, across nine
stages. The exact two source/hook/image proofs are
`evidence/reliability-rc3-offline.json` and its `-llvm18` counterpart. The new
6.097 BIN/USB files reproduce byte-for-byte under `firmware/candidates/06.09-rc3/`.
Its owner-authorized native transfer completed and the remote accepted it.
The owner repeatedly reports delayed response. Passive input confirms Bluetooth
front arrows and keyboard alongside infrared. A later six-read ATT sequence
confirmed actual 6.097 in 454 ms; all full diagnostic pages were
`00000BFFFFFFFFFF1306`: inactive, latest deferred refusal 11, native TX not
quiescent at role 6 before bond/heap queries. No guard was forced. See
`evidence/hardware-6097.json` and the additional active-path prefix measurements
in `evidence/stack-review-6097-active.json`; no full ROM/RTOS stack claim is made.

Historical 6.095 assets and their 134-check proof are immutable. The 6.097 source
adds event-driven guarded admission and the hardware-confirmed one-byte Blue
correction. Diagnostic 6.097 records the latest refusal and its boot/deferred
scope in the existing buffer. Its 6.098 contingency package retains only 06.07
behavior and has 15 separate narrow checks. The owner authorized 6.097 and,
only if the trial fails, recovery 6.098. That recovery completed after the failed
trial. Native and independent reads confirm actual 6.098, six ATT reads passed
with status 0 in 622 ms, and the owner reports both faces working again. See
`evidence/hardware-recovery-6098.json`. Exact response latency and long idle
remain unqualified.
The compiled 06.10 image remains withheld.
Public hashed inputs and logs use LF.

The hardware follow-up and `evidence/admission-review-6097.json` identify an
unqualified liveness boundary: native readiness persists after drain and may be
set before APP sees a connection event. The 6.097 guard can therefore preserve
fallback indefinitely. The 155 offline checks do not establish activation under
this real ordering. A future handoff needs explicit exclusion of both native HID
reader and an APP producer already inside 0x4FAA. The 6.099 offline handoff addresses this boundary; no new candidate is installed. The cause of reported response delay is unknown.

## Implemented

The actual freestanding C core and native adapters compile for Cortex-M3. The
single native allocation is **640 bytes** (488-byte core plus adapter state,
including 16 source timestamps and native pending-key provenance). All source and report queues hold 16 copied
entries. A 768-byte free-heap reserve is checked after allocation. No unclaimed
RAM address is used for the state: the old queue's exclusively claimed storage
holds only its checked marker and native allocation pointer.

Source, TX and native pending rear presses expire after 2 seconds; releases remain protected.
One HID worker handles IDs 1/2, including pairing cleanup neutrals. Native forced
erase remains synchronous because its caller can immediately reset. Original
non-HID notifications, voice, audio, OTA and power parameters remain native.

The native HID task has 400 bytes of stack, APP has 750. Full bond/NV queries
run only in APP. The current independent review observes APP prefixes up to 232 bytes, worker/core prefixes up to 292 bytes and a separate expanded native HID path up to 312 bytes before helper 3438. These already include their stated native frames. The apparent 88-byte HID remainder is **not a proven ROM/RTOS/IRQ margin**. Initialization, adapter and core tests check preserved
registers, SP and memory boundaries. Real stack headroom still needs observation.

06.09 exposes three brief diagnostic pages, including the last valid front scan index
for physical button mapping. The rc2 follow-up also records refusal codes 1–10,
bond count and sampled free/largest-block memory in the existing 21-byte Hardware
Revision buffer. That historical rc2 snapshot stays frozen; rc3 records
the latest actual boot/deferred admission refusal, reason 11 included. Diagnostic
reads themselves never query BLE/NVRAM/heap or retry admission. Unknown state after a lost claim reports unknown provenance.
No extra state allocation or relaxed guard is introduced. Admission retries
are limited to useful lifecycle transitions and, in 6.099, proven useful rear releases at188C; presses, timers and diagnostic reads do not retry. 06.10 restores the original Device
Information callback and removes diagnostic heap sampling/activity accounting.
The versioned decoder opens no connection. Shared functional safety counters stay
internal. Neither build is represented as a normal-use release.

The optional native TV app is implemented with no production dependency or
Internet/Bluetooth permission. Its service requires manual Accessibility activation
and its preset starts disabled. The user activated the service during this session;
profile activation remains a separate explicit choice in the app.
`evidence/companion-device.json` records the installed APK hash, six explicit action
launches, JSON round-trip and final disabled preset/three-item dock. Actual gesture
dispatch with an enabled profile and physical HDMI video/port confirmation remain pending.

## Requirement-to-evidence mapping

| Requirement (user wording) | Evidence |
| --- | --- |
| “file de 16 événements copiés” / “orientation puis touche” | `test_source_fifo_order_and_overflow_repair`, `test_thumb_state_layout_full_source_fifo_and_overflow_neutralization`, `test_uart_every_split_survives_actual_irq_worker_and_preserves_orientation_key_order`. The last executes the real UART parser and verifies orientation/front before a later rear event. |
| “un seul gestionnaire de transmission” / “après son acceptation par la pile” | `test_both_report_paths_use_actual_notify_wrapper_and_full_keyboard_deduplication`, `test_allocation_failure_retains_report_and_caches_until_native_retry_accepts`; native callee inventory in `firmware/NATIVE_ABI.md`. Acceptance means the native stack accepted a notification, not delivery ACK from Android. |
| “accepté, échec temporaire, indisponible” / “caches” | `test_allocation_failure_retains_report_and_caches_until_native_retry_accepts`, `test_unavailable_waits_for_useful_event_and_native_readiness_callback_wakes_once`. Native last-sent caches update only after status zero. |
| “16 rapports en attente” / “protection séparée des relâchements” | `test_mixed_saturation_protects_independent_release_mailboxes`, `test_notification_allocation_failure_at_each_of_sixteen_queue_positions`, `test_overflow_during_inflight_press_repairs_after_acceptance`. |
| “deux secondes” / “20, 50, 100 puis 200 ms” / “sans boucle permanente” | `test_retry_delays_budget_two_seconds_and_clock_millisecond_wrap`, `test_source_queue_press_expires_before_dispatch_but_release_and_uart_ack_survive`, `test_transient_backoff_and_release_recovery_after_event`. Source timestamps prevent stale input being given a new TX lifetime. |
| “génération de connexion” / “état neutre” / “Ne jamais rejouer une commande Alimentation” | `test_disconnect_pair_change_and_unknown_peer_never_replay_power`, `test_peer_change_between_source_pop_and_report_admission_drops_old_event`, `test_new_connection_handle_without_intermediate_callback_still_purges_old_command`, `test_cccd_disable_reenable_purges_old_taps_and_sends_neutral_first`, `test_thumb_accepted_power_press_has_one_flight_and_never_replays`. |
| “accumulateur borné de six octets” / “retrouver l’en-tête FE” | `test_uart_fragments_resynchronization_and_index_guard`, `test_thumb_parser_fragments_embedded_fe_resync_and_all_index_bounds`, `test_full_bad_uart_frame_rearms_next_irq_and_timeout_discards_fragments`. No invented checksum. Native UART parameters are byte-identical. |
| “Refuser les index avant 45 à 254” / “0 à 44” / “255” | `test_every_front_index_and_release_execute_real_decoder_and_report_pipeline`, `test_thumb_parser_fragments_embedded_fe_resync_and_all_index_bounds`, native invalid-source tests in `test_native_dispatch.py`. |
| “Vérifier les quatre touches de couleur sur le matériel” / “corriger le doublon bleu/jaune uniquement après confirmation” | `evidence/hardware-colors-6096.json` confirms physical Red/Green/Yellow/Blue indexes 19/12/1A/1B and the duplicate006C. `test_declared_blue_fix_is_one_flash_byte_and_preserves_the_other_44_rows` and `test_confirmed_color_scans_read_flash_into_app_ram_and_release_in_order` prove the targeted source correction. It is not installed; corrected radio output remains unqualified. |
| “Comparer le rapport clavier complet” | `test_keyboard_compares_all_eight_bytes_and_validates_lengths`, `test_both_report_paths_use_actual_notify_wrapper_and_full_keyboard_deduplication`; extra key-slot difference yields a second real report. Physical extra-slot impact remains unestablished. |
| “primitives critiques natives” / “Aucun appel Bluetooth, allocation ou attente” | Every runtime fixture checks native gate depth/token and rejects allocation, heap/peer queries, BLE and RTOS posts inside the gate. `test_native_task_stack_sizes_and_hid_inline_prefix_are_explicit` rejects bond/NV queries in HID. These are explicit interleavings, not electrical IRQ/scheduler simulation. |
| “une allocation native unique plafonnée à 640 octets” / “768 octets” | `test_initialization_claims_only_after_one_bounded_allocation_and_preserves_registers`, `test_heap_prechecks_postfree_reserve_and_allocation_failure_leave_native_queue_intact`, `test_missing_identity_handles_or_active_native_queue_never_claim_storage`. Tests cover null allocation, fragmentation, insufficient total and 767/768 boundary. |
| “conserver les chemins 06.07” / “améliorations ne sont pas actives” | Native prologue/bridge/fallback tests, initialization failure tests and `test_native_fallback_is_explicit_and_does_not_present_fake_zero_metrics`. Inactive diagnostic page reports fallback; old queue remains untouched on failure. |
| Diagnose the observed inactive first candidate | `test_inactive_diagnostic_records_each_refusal_and_round_trips_actual_gatt_pages` executes all ten refusal paths through compiled C, three actual callback reads and the decoder. `test_inactive_diagnostic_reads_freeze_boot_reason_without_queries_or_allocation_retry` checks frozen provenance; `test_lost_claim_cannot_reuse_a_boot_refusal_or_active_page_as_failure_provenance` checks unknown provenance. Usage initialization success/failure tests preserve the stock Hardware Revision buffer. |
| “Si l’allocation échoue, conserver les chemins 06.07” / “une allocation native unique plafonnée à 640 octets” | `test_retry_refusals_record_latest_reason_and_phase_without_changing_legacy_or_querying_on_reads`, `test_ordinary_wakes_and_active_reentrant_events_never_allocate_again`, `test_stack_handoff_preserves_real_last_report_during_admission_before_and_after_precheck`. Refused transitions keep the queue intact; an in-flight native last slot is resumed with its payload preserved. |
| Observed boot count0: defer admission without repeated key/timer retries | `test_boot_without_bond_admits_after_connection_event_and_neutralizes_both_reports`, `test_only_changed_successful_lifecycle_events_post_the_coalesced_admission_bit`, `test_pairing_success_with_persistent_native_readiness_admits_without_timer_polling`. Native initialization still executes once. |
| Versioned refusal provenance; no diagnostic allocation or persistent reader | `test_latest_admission_scope_flag_is_versioned_and_unknown_provenance_stays_unknown`, `test_each_new_useful_transition_updates_last_refusal_and_success_enables_active_pages`, `test_historical_quiescence_reason_cannot_be_relabelled_as_another_diagnostic_version`.6.097 reserves reason11; 6.099 reserves reason12. Both permit latest-deferred flag10. |
| “audio, OTA et bootloader restent ceux d’origine” / “voix” / “appairage” | Builder validates every modified range against stock. `test_native_dispatch.py` compares native voice, holds, pairing and real rear letter/shift/release behavior with published 06.07. Physical voice and update-mode heap margins remain pending. |
| “écran d’apprentissage” / “profils locaux” / “ouvrir une application” / “HDMI 1/2” | Native app source and 22 host tests; actual installation, focus/editor and JSON fallback observed on TV. See `app/.testagent/status.md` for device evidence and action-specific remaining checks. |
| “Ce profil reste désactivé” | `testDisabledColorPresetAndReset`, `testProfileCloneIsDisabledAndBindingsIndependent`; disabled profile observed on the TV before and after JSON round-trip. |
| “600 ms” / “300 ms” / “double appui désactivé par défaut” | `testLongExactlyAt600AndNoShortOrRepeatAction`, `testDoubleWindowAndSingleDeadline`, `testSecondDownAtDeadlineStartsNewSingle`, `testLongWinsOverDoubleAndDoesNotEmitShort`. |
| “aucun délai aux touches ordinaires” / “touches non configurées passent” | `testProtectedKeysNeverBindOrIntercept`, `testCompanionForegroundDoesNotCapture`, `testProfileChangeCancelsActionButConsumesOwnedRelease`, `testCanceledReleaseAndOrphanEventsPassthrough`. |
| “export/import JSON versionné et remise à zéro” / “Aucun contenu d’écran” | JSON round-trip/rejection/reset host tests and APK manifest assertions; real TV lacks a usable document picker, so explicit JSON text/copy/paste is implemented and exercised. No screen-content retrieval, account, server, periodic polling or GATT connection. |
| “Le firmware reste utilisable sans cette appli” | Firmware contains no app/network protocol dependency. Full HID integration tests execute without Android. Hardware use remains pending for these candidates. |
| “temps de connexion, d’activité UART et de veille” / “pas comme un gain d’autonomie démontré” | `test_heap_and_uart_activity_samples_track_transitions_without_power_claim`, diagnostic decoder tests. These are sampled heap and logical UART flags, not measured sleep current. No RF power or native power timing is changed. Before/after physical measurements remain pending. |
| “hash d’origine” / “octets attendus” / “plages modifiées” / “taille, les vecteurs et le CRC” | 13 builder tests, exact manifest instruction checks and deterministic USB test; changed source/hook/image evidence is rejected. `test_qualification_rejects_failed_unstable_or_incomplete_proof_with_valid_hash` also rejects 25 cases of failed, unstable or incomplete proof despite a valid JSON hash. |
| “Aucun flash automatique” / “50 %” | Verify/build/decoder contain no device deployment path. Every non-whitelisted stock byte is preserved, including native battery/update logic. No flash, deliberate interruption, low-battery bypass or programmer-recovery claim. |

## Limits and remaining acceptance

- 6.097 is an offline-qualified experimental candidate, not a hardware-qualified
  replacement. Native lifecycle/admission stack observations exclude ROM/IRQ
  worst cases. Its inactive diagnostic can change across separate partial ATT
  reads if a new useful transition occurs; prefer complete 20-byte reads.

- `evidence/hardware-0609-rc1.json` confirms the first 06.09 installation and
  three all-zero inactive snapshots. Both faces were reported responsive but
  irregular; those observations do not qualify the inactive reliability core.
  The rc1 reason remains unknown. The rc2 snapshot confirms an initial bond
  count0 refusal before allocation. After host re-pair, actual6.095 and its
  frozen inactive snapshot are verified; allocation/heap and grouped checks
  remain unqualified. No activation guard was forced or relaxed.
  06.10 normal-use qualification waits for successful hardware acceptance.
- Real heap reserve during keyboard/voice/update, full native stack headroom,
  all physical keys and corrected-color behavior, radio delivery and independent short/long/double
  shortcuts need the physical session. Mocked native APIs cannot replace it.
- First press/wake after 30 minutes and one night must run without a diagnostic
  client. A failed 06.07 wake after a long pause was reported during this session;
  the TV host was independently observed disconnected with no active HID device.
  Reconnection improvements are tested offline, not yet proven on this remote.
- Native 32-bit 10 µs clock differences cover one wrap; longer unobserved
  intervals cannot be reconstructed exactly. Activity counters do not establish
  battery life. Private/multiple peer identities are not qualified.
- `test_rear_pending_scan_code_expires_from_original_source_timestamp`,
  `test_rear_pending_scan_code_never_crosses_connection_epoch`,
  `test_rear_release_cancels_native_pending_scan_code_while_uart_is_unready`
  and `test_untracked_native_pending_scan_code_is_cleared_without_replay`
  cover the additional native APP+17 buffer; its valid replay at 1999 ms is preserved.
- Unicorn 2.1.4 write hooks disturb both the factory unaligned `memcpy` IT loop
  and Clang 18's conditional `STRB` repair loop. With the same real Clang 18
  instructions, an empty write callback reproduces both CI stalls; removing it
  returns correctly. Adding an instruction callback does not fix the engine bug.
  Native runtime and standalone core checks compare the entire RAM at call
  boundaries. The core also protects flash and the return page as read/execute;
  `test_thumb_ram_guard_rejects_real_store_outside_reviewed_ranges` executes real
  forbidden stores and requires the RAM rejection or `UC_ERR_WRITE_PROT`.
  ABI, sentinels, instruction/time budgets and behavioral assertions are unchanged.
  Initialization/diagnostic paths retain their direct write guards. Boundary RAM
  comparisons do not detect a transient write restored before return.
