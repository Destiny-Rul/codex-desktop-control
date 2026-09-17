# Reusable single-slot lifecycle

Two-cycle repeated use was independently accepted on Desktop 26.908.9136.0.
v0.3.15 enables enqueue only with current profile certification and the exact
build/hash/protocol gate documented in `native-queue.md`. Local reconciliation
and receipt-backed reuse require no live write authorization; no cancel or scheduler exists.

## Persisted proof and state transitions

Before any enqueue IPC, the controller validates the database-mapped rollout
path under Codex home, its `session_meta` thread identity, and a complete record
boundary. Intent persists that byte offset and prefix SHA-256. Status examines
only complete records after this baseline. It verifies path/identity, prefix
integrity, and the last successfully correlated read checkpoint.

Only `event_msg/item_completed` with `item.type="UserMessage"` and
`item.client_id == queue item ID` establishes correlation. That record must also
contain this thread ID, a valid turn ID and native message ID. Exactly one
`task_started` for that turn must precede it. A later exact `task_complete`,
`task_failed`, `turn_aborted` or `turn_interrupted` proves the corresponding
terminal state. `task_complete` carrying an error is rejected. No prompt, marker,
timestamp, owner ID or item disappearance supplies a substitute mapping.

Malformed JSON/event records, partial trailing records, truncation/rewrite,
wrong thread/path, duplicate mappings (even identical repeats), duplicate or
out-of-order lifecycle evidence all leave the slot unknown/reserved. A partial
tail can be re-read after the writer finishes; no native submission is retried.
An uncertain IPC submission can become running/terminal only through this same
exact persisted proof. A changed owner or silent passive observation does not
override valid persisted evidence. A prior unmanaged-entry conflict is sticky.

Status never mutates the native queue or sends/replays an item. Without
`--observe` it does no IPC at all. An unresolved legacy intent without a saved
baseline remains reserved, regardless of matching-looking text or turn times.

## Archive then release, under the shared lock

The existing canonical Codex-home/thread mutex covers the entire status
read/reconciliation/archive/release transaction. It is shared across profiles,
processes and certification; certification's receipt -> thread order is unchanged.

Terminal receipts reside alongside the ledger in `<slot hash>.history/<item ID>.json`.
They contain exact original mapping/start/terminal records, baseline, item and
identity. The controller flushes/fsyncs a temporary receipt and publishes with
a no-replace hard link, then atomically persists `slot_reserved:false` in the
ledger. The slot file is not deleted. Receipt publication failure retains the
reservation. Crash after publication is recoverable: status verifies the identical
archive before finishing release. Existing archives are never overwritten.
This is controller-enforced immutability, not protection against administrator
file edits; the saved receipt hash is checked before reuse. Tampering/missing
history blocks reuse. Filesystem power-loss durability remains platform-dependent.

After release, the next explicit enqueue may omit `--adopt-empty-exclusive` if
exclusive-management provenance remains valid, the pinned build is unchanged,
and its terminal receipt verifies. It creates a fresh ID and baseline and keeps
prior history. A nonempty observed queue still blocks the setter. Re-adoption
cannot override unmanaged conflicts or uncertain reservations. No automatic
enqueue, cancellation, slot deletion or force reset is provided.

## Legacy intent migration

The first trial predates persisted baselines in queue intent. Its saved
pre-submit baseline can be explicitly imported once:

```powershell
python skills/codex-desktop-control/scripts/desktop_controller.py --hermes-home $HermesHome --profile $Profile --desktop-codex-home $DesktopCodexHome queue status --thread $Thread --baseline-evidence $SavedBaselineJson
```

The saved artifact must contain `thread`, `rollout_bytes`, and
`settings.rollout_path`. The controller validates thread/path/record boundary,
stores the artifact hash and current prefix hash, then uses normal exact
reconciliation. This explicit migration trusts the supplied historical baseline;
it cannot retrospectively prove that the historical prefix was never rewritten.
It never derives a baseline from matching prompt/time, defaults to byte zero,
or replaces an already established baseline. No IPC is needed.

## Bounded two-cycle dedicated-thread acceptance

This procedure passed before v0.3.14 finalization. A new installation must first
obtain its own current-version profile certification; historical receipts must
not be copied. Further live acceptance requires explicit user authorization.

Use only the user-designated dedicated test thread. Use existing runtime gates
and omit all model/effort overrides. Keep all queue editing controller-managed.
No install or gate bypass is allowed.

1. Read-only verify idle/unarchived owner and inspect local status. The prior
   trial must already be terminal/released with its immutable receipt intact.
2. Start one harmless 20-second starter task using the real session tool. Confirm
   its exact turn is running; stop if it already completed. Enqueue one uniquely
   marked plain-text follow-up **without re-adoption**.
   Save new item ID, baseline, acknowledgement and owner observation.
3. A second enqueue while reserved must fail before IPC. Observe the starter's
   actual completion and distinct queued turn. Run local status until exact
   `client_id` correlation and terminal evidence archive/release the slot.
   Stop on uncertainty; never retry native enqueue or clear the ledger.
4. Repeat steps 2–3 exactly once, with fresh markers and no adoption flag. Confirm
   a fresh native item/turn and a second immutable receipt. Verify both new
   receipts and the original trial receipt remain unchanged and final slot is free.
5. Collect bounded rollout/owner/controller receipts and renderer logs, and compare
   settings before/after. Report ResizeObserver warnings separately with timing;
   do not make generic zero-console-errors a functional prerequisite. A two-cycle
   observation is not exhaustive concurrency proof. Stop at the acceptance boundary.
