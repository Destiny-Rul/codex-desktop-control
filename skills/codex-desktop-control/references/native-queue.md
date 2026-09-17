# Native single-slot queue

Repeated-use enqueue/status was independently accepted on the prior exact pin.
The current exact pin has independently verified native structure but awaits the
bounded one-cycle acceptance below.
Every enqueue requires ordinary valid certification in the selected profile for
the current Skill version, Desktop identity and schema, then the exact queue build,
archive hash and method versions. Exclusive adoption/provenance and a safe slot
are additionally mandatory. `--acceptance-test` remains a legacy label only and
bypasses nothing. No separate queue receipt is required: the shipped pin records
the accepted implementation boundary, not certification of another profile.
The current pin upgrade requires a bounded one-cycle queue acceptance; no live
queue mutation or installation accompanied it. Broader builds are not queue-certified.

## Contract and commands

At most one controller-owned unresolved message per canonical Codex home/thread.
No manual/UI queue edits or other queue producers are allowed. Ordinary native
queue consumption is expected. This exclusive-management contract makes the
whole-array follower setter admissible; it does not make the setter atomic with
manual edits. If this contract cannot be maintained, do not use this feature.

From the repository, use the existing installation's explicit paths/profile:

```powershell
python skills/codex-desktop-control/scripts/desktop_controller.py --hermes-home $HermesHome --profile $Profile --desktop-codex-home $DesktopCodexHome queue enqueue --thread $Thread --prompt $Prompt --adopt-empty-exclusive
python skills/codex-desktop-control/scripts/desktop_controller.py --hermes-home $HermesHome --profile $Profile --desktop-codex-home $DesktopCodexHome queue status --thread $Thread
python skills/codex-desktop-control/scripts/desktop_controller.py --hermes-home $HermesHome --profile $Profile --desktop-codex-home $DesktopCodexHome queue status --thread $Thread --observe
```

No queue cancel, reset, overwrite, retry, settings or model options are exposed.
See `queue-lifecycle.md` for local reconciliation, immutable history, and the
two-cycle acceptance procedure. Normal status reconciles local rollout evidence;
`--observe` additionally performs a bounded read-only owner broadcast observation.
The first-use `--adopt-empty-exclusive` flag attests that the designated thread's
visible queue has independently been verified empty (including any server-backed
entries) and that all future queue editing is controller-managed. Owner discovery
does not supply that verification. Silence in passive broadcast history cannot
replace it. First use without this attestation fails before IPC. Any nonempty or
malformed owner queue observation before the setter blocks the write, even if a
subsequent broadcast is empty. No observed entries are copied or reinserted.

## Reservation, persistence and status

The canonical-home/thread hash names a JSON intent under
`<canonical Codex home parent>/.codex-desktop-control-queues/`. This is separate
controller-owned storage, outside Codex home, shared across Hermes homes and
profiles. Do not delete/move/edit it to unblock an uncertain operation. It contains
the prompt; treat it as private local runtime data. Queue path links/reparse
points are rejected. Existing Codex databases/global-state are never written.

The OS-released canonical thread mutex is the same key used by certification.
Certification lock order remains receipt -> thread. Queue takes only thread;
it holds that lock through validation, intent persistence, IPC and final status
persistence. A contender fails before IPC. Intent is flushed/fsynced before IPC;
Windows replacement is atomic and POSIX also fsyncs the containing directory.
Hardware/power-loss durability still depends on the filesystem. Process death
releases the mutex, not the durable reservation. A second enqueue fails while
a reservation remains pending/unknown, including malformed records. Exact
correlated terminal evidence is archived before the slot is marked released.
The ledger remains on disk; it is not deleted. Even explicit
no-client-found is not retried by queue operations.

- `unadopted`: no controller intent; native contents are unknown, not empty.
- `enqueued`: an owner broadcast contained exactly this native item ID. This is
  an observation, not a revisioned current snapshot, start receipt or completion.
- `unknown`: no broadcast, item disappeared, owner changed, malformed response,
  conflict or uncertain write, without exact rollout lifecycle evidence. The slot
  remains reserved. Exact evidence takes precedence over broadcast silence.
- `running`: exact baseline-scoped native client-ID mapping and ordered task start.
- `completed`, `failed`, `interrupted`: the exact mapped turn has terminal evidence;
  immutable archival precedes release. Interrupted is never called completed.
- `setter_acknowledged:true`: `{ok:true}` returned by the setter; independent of
  whether the item was ever observed pending. Idle native execution is allowed.

Plain status reconciles the local persisted rollout. Saved native observations
are historical. `--observe` opens a bounded
read-only connection; silence remains unknown. A failed/missing acknowledgement
does not cancel a possible submission. Status never sends the setter or replays
an item. No turn ID is inferred from text, time, or item disappearance. The native
execution path uses `clientUserMessageId = item.id`. Live acceptance established
its persisted representation: `event_msg/item_completed`, `item.type=UserMessage`,
`item.client_id`, with explicit thread and turn IDs. Status uses this exact mapping,
never prompt text/time inference. See `queue-lifecycle.md`; no manual reset exists.

## Inspected native construction and acknowledgement

Pinned Desktop: `26.911.7940.0`, app.asar SHA-256
`74e7aaf2c112f84ef68a7846d10d1411403e72763f7e93fe046df2f264adf6e0`.
Both method versions are independently checked: setter v1 and broadcast v2.
Any other build/capability is rejected, even if ordinary send is certified.

The following historical evidence offsets are zero-based decoded characters in
`webview/assets/app-initial-bcc2ff475eb6.js`:

- `H1t` ~2357643: request `thread-follower-set-queued-follow-ups-state`,
  `{conversationId,state:{[conversationId]:[item]}}`, targeted owner.
- `wGt` ~2086285: asserts owner, awaits `acceptFromFollower`, returns `{ok:true}`.
- `#f` ~2354300: persists replacement then broadcasts messages. Broadcast failure
  is logged, not propagated as setter failure: ack and observation are separate.
- `F1t` ~2339358 rejects untrusted app context. Its imported `an` is `Ln` from
  `src-996ff3571e1f.js`, exported `lv` at 145790: checks `untrustedAppMessage` or
  untrusted `mcpAppModelContextAttachments`. Plain controller context has neither.
- Native constructors at ~2281909 and ~2924400 establish `id,text,context,cwd,
  createdAt`. Controller context supplies `prompt,addedFiles:[],fileAttachments:[],
  ideContext:null,imageAttachments:[],workspaceRoots:[verified cwd]`; no optional
  attachment or permission overrides are fabricated.
- `i4t` 2389559 consumes this context; `l4t` 2390678 prepares execution using
  Desktop settings, and ~2392400 passes `clientUserMessageId:l.id`.
- `pFt` [1850484,1851476) produces plain input
  `{type:'text',text:prompt,text_elements:[]}`. The offline fixture executes that
  exact extracted function. `text_elements` belongs to generated turn input,
  not a made-up follower queue-item field. Native `Sv` also formats context/text.

The bridge uses authoritative `thread-owner-discovery` (no following-announcement
fallback), checks owner stability, rejects observed preexisting entries, sends
exactly one setter, then waits briefly for v2 broadcasts from that owner and
local host/thread. No send, steer, settings, app-tool follow-up, alternative
app-server, feature flag or direct state write is used. Passive broadcasts have
no revision; they cannot prove an authoritative current empty queue.

## Bounded one-cycle acceptance after a pin upgrade

Use only the already user-designated dedicated test thread with its released slot
and intact exclusive-management provenance. Do not re-adopt, reset or edit history.

1. Verify the selected profile has valid ordinary current-version certification for
   Desktop `26.911.7940.0` and migration 55. Read local queue status and require
   the prior slot to be terminal/released with its immutable receipt valid. Verify
   the thread is unarchived, idle and has no manual queue edits; preserve settings.
2. Start one uniquely marked harmless bounded task through the existing Codex
   session. Confirm its exact turn is running before proceeding. If it finishes
   before enqueue, record zero queue writes and stop rather than retrying blindly.
3. Enqueue exactly one uniquely marked follow-up without
   `--adopt-empty-exclusive`. Save the controller response, native item ID, owner,
   setter acknowledgement and observation. Never retry an uncertain submission.
4. Attempt a second enqueue while reserved. It must fail before IPC. Observe the
   starter complete, then a distinct next turn. Run local queue status until exact
   persisted `UserMessage.client_id == item.id` mapping and exact terminal evidence
   archive the receipt and release the slot. Item disappearance alone proves nothing.
5. Verify all prior immutable history hashes are unchanged, the new receipt is
   immutable, the final slot is released, and model/effort are unchanged. Collect
   bounded rollout/controller receipts and test-window renderer logs. Report exact
   IDs/order and any new error boundaries separately, then stop after this cycle.

## Historical initial single-trial procedure

The initial trial ran on 2026-09-16; functional ordering and exact persisted
correlation passed. ResizeObserver warnings were separately recorded, including
before enqueue. The following was that trial's procedure; it is not the current
repeated-use acceptance instruction (see `queue-lifecycle.md`).

1. Set `$Thread` to the explicitly user-designated dedicated test thread (never
   a packaged/default thread ID). Confirm it exists,
   is open/unarchived and idle using read-only tools. If unrelated work is busy,
   stop. Independently verify its visible queue has no local or server entries;
   establish exclusive controller queue management before adoption. Keep model
   and thinking unchanged and use the existing profile dependencies.
2. Through the real session tool, send to that thread only (omit settings):
   “Queue acceptance starter QSTART-<unique>: run one harmless 20-second sleep,
   then reply QSTART-<unique>-DONE. Do not edit files, change settings, send
   messages or use other threads.” Verify its exact turn ID is running before
   enqueue. If it already completed, stop this trial; do not pretend it was busy.
3. Set `$Thread` to that dedicated ID and `$Prompt` to
   “Reply only QNEXT-<unique>-DONE. Do not use tools or edit files.” Run the first
   command above once. Save JSON: item ID, intent time, owner, setter ack and
   observation. Do not retry failures, even if the visible queue looks empty.
4. Attempt a second enqueue (same thread; optionally another existing profile).
   It must report reserved without sending IPC. Inspect status; if still pending,
   verify the visible native item once. Do not edit it or invoke cancellation.
5. Observe starter completion (not interruption), then the distinct next turn's
   start and exact final marker. Save both turn IDs and ordered events. Where
   native client-message ID evidence is available, save it; do not infer exact
   correlation solely from the marker. Check Desktop renderer logs for errors.
   A one-off ordering observation is not proof of all concurrency behavior.
6. Run bounded `queue status --observe`. An empty/silent observation must remain
   unknown with the slot reserved and turn_id null, even if the human observed
   completion. Stop and hand off evidence; do not clear the receipt or run a
   second trial. Live acceptance does not automatically unlock production.
