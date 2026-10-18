# Reliability and companion verification

Scope: software implementation and offline integration; **not hardware qualification**.
The published 06.07 remains unchanged. The first 06.09 was installed with the
owner's explicit approval, but reports inactive fallback on the test remote.
The 6.095 (06.09 rc2) refusal-diagnostic transfer completed with owner authorization.
Its actual installed revision and adapter state remain unconfirmed because bounded
reads cannot yet return an ATT value. See `evidence/hardware-6095.json`.
06.08 is not a build input. Exact test IDs and hashes are in
`evidence/reliability-rc2-offline.json`; the complete command is `python firmware/verify.py`.

Delivery: 134/134 checks pass across nine stages with LLVM 18 and 19. Exact diagnostic and usage
image hashes match the public proof; the evidence gate is checked again after binding.
The 6.095 BIN/USB archive was reproduced byte-for-byte and is available under
`firmware/candidates/06.09-rc2/`. The manifest is sanitized; checksums include it.
The compiled 06.10 image remains undistributed pending hardware acceptance.
Public hashed inputs and logs use LF so Git checkout cannot invalidate the proof.

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
run only in APP. Tests observe a 240-byte HID prefix and a 320-byte visible
RPC chain before ROM/context; the remaining 80 bytes are **not a proof of the
hardware worst case**. Initialization, adapter and core tests check preserved
registers, SP and memory boundaries. Real stack headroom still needs observation.

06.09 exposes three brief diagnostic pages, including the last valid front scan index
for physical button mapping. The rc2 follow-up also records refusal codes 1–10,
bond count and sampled free/largest-block memory in the existing 21-byte Hardware
Revision buffer. Inactive reads preserve that boot snapshot without querying BLE,
NVRAM or the heap. Unknown state after a lost claim reports unknown provenance.
No extra allocation, retry or relaxed guard is introduced. 06.10 restores the original Device
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
| “Vérifier les quatre touches de couleur sur le matériel” | `evidence/hardware-colors.json`: after rear Space reconnected Bluetooth, Red/Green/Yellow/Blue produced Linux Red/Green/Yellow/Yellow on the Bluetooth input. The duplicate is confirmed; the internal index is still unknown because a temporary GATT read did not connect. **No color mapping patch applied.** 06.09 exposes the last front index for the next physical check. |
| “Comparer le rapport clavier complet” | `test_keyboard_compares_all_eight_bytes_and_validates_lengths`, `test_both_report_paths_use_actual_notify_wrapper_and_full_keyboard_deduplication`; extra key-slot difference yields a second real report. Physical extra-slot impact remains unestablished. |
| “primitives critiques natives” / “Aucun appel Bluetooth, allocation ou attente” | Every runtime fixture checks native gate depth/token and rejects allocation, heap/peer queries, BLE and RTOS posts inside the gate. `test_native_task_stack_sizes_and_hid_inline_prefix_are_explicit` rejects bond/NV queries in HID. These are explicit interleavings, not electrical IRQ/scheduler simulation. |
| “une allocation native unique plafonnée à 640 octets” / “768 octets” | `test_initialization_claims_only_after_one_bounded_allocation_and_preserves_registers`, `test_heap_prechecks_postfree_reserve_and_allocation_failure_leave_native_queue_intact`, `test_missing_identity_handles_or_active_native_queue_never_claim_storage`. Tests cover null allocation, fragmentation, insufficient total and 767/768 boundary. |
| “conserver les chemins 06.07” / “améliorations ne sont pas actives” | Native prologue/bridge/fallback tests, initialization failure tests and `test_native_fallback_is_explicit_and_does_not_present_fake_zero_metrics`. Inactive diagnostic page reports fallback; old queue remains untouched on failure. |
| Diagnose the observed inactive first candidate | `test_inactive_diagnostic_records_each_refusal_and_round_trips_actual_gatt_pages` executes all ten refusal paths through compiled C, three actual callback reads and the decoder. `test_inactive_diagnostic_reads_freeze_boot_reason_without_queries_or_allocation_retry` checks frozen provenance; `test_lost_claim_cannot_reuse_a_boot_refusal_or_active_page_as_failure_provenance` checks unknown provenance. Usage initialization success/failure tests preserve the stock Hardware Revision buffer. |
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

- `evidence/hardware-0609-rc1.json` confirms the first 06.09 installation and
  three all-zero inactive snapshots. Both faces were reported responsive but
  irregular; those observations do not qualify the inactive reliability core.
  The reason is unknown. The rc2 follow-up records refusal provenance without
  forcing activation. The 6.095 USB transfer completed, but actual version and
  diagnostic confirmation remain pending alongside the grouped session.
  06.10 normal-use qualification waits for successful hardware acceptance.
- Real heap reserve during keyboard/voice/update, full native stack headroom,
  all physical keys/colors, radio delivery and independent short/long/double
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
