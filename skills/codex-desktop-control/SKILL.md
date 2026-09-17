---
name: codex-desktop-control
description: Safely control existing Codex Desktop tasks on Windows.
version: 0.3.15
author: Destiny-Rul
license: MIT
platforms:
  - windows
metadata:
  hermes:
    tags: [codex, desktop, windows, ipc, automation]
    skill_data: "$HERMES_HOME/skill-data/codex-desktop-control/profiles/<profile>"
    entrypoint: scripts/desktop_controller.py
    doctor: scripts/doctor.py
---

# Codex Desktop Control

Control an already-running Codex Desktop task through its structured Windows IPC. Use only the bundled scripts and explicit absolute configuration; never install this source package into Codex or copy credentials into the Skill.

## Collaboration workflow

- Hermes handles fast tasks directly. For necessary complex work, prefer Codex Desktop and minimize use of Hermes built-in subagents.
- Codex Desktop may decide autonomously whether to use its own subagents while executing a task; Hermes does not need to authorize each Codex-internal subagent.
- After obtaining the user's consent, Hermes may control one or multiple Codex Desktop threads that the user explicitly designates. Keep every operation scoped to those threads; never select a thread or expand the controlled set on the user's behalf.
- Write Codex task prompts primarily in English, request use of FastCtx once, and leave model and reasoning settings under user control. Do not set or change them unless the user explicitly requests it.
- Prefer direct requests such as "Please inspect..." or "Please implement..." rather than framing instructions as "The user needs...".
- Continually refine control prompts from Codex's replies and observed execution. Keep English-first, direct requests; adapt wording and detail to be precise and concise, rather than repeating a rigid template. Prefer one bounded, verifiable stage at a time. Finish each stage with real evidence, not a half-finished deliverable, and stop at its acceptance boundary without inventing extra work or expanding the authorized scope.
- Split complex work into meaningful, verifiable stages. Provide the overall goal and necessary context, but dispatch only the current stage; review its results before giving the next stage. Do not fragment simple tasks unnecessarily.
- Immediately after dispatch, start exactly one task-appropriate controller `wait` as a non-blocking background job. Hermes may continue working or communicating in parallel and may inspect progress or steer the active turn when needed, but must not call `process(wait)` to block on that waiter. At most one waiter may be active for a job at any moment.
- Treat a wait timeout as a review gate, not as task failure: inspect current state, decide whether to keep waiting or steer, and communicate material progress.
- When Codex completes, Hermes independently reviews and accepts the returned artifacts. If rework is required, repeat the dispatch, single background wait, and independent acceptance cycle.
- When Hermes does not understand the user's intent within this Skill's Codex-control scope, or a material ambiguity would affect a Codex control, monitoring, or acceptance decision, call the Hermes `clarify` tool and present selectable options instead of guessing or pretending to understand.
- If owner discovery reports `no-client-found` because a user-designated thread is not open or visible in Codex Desktop, stop before any state-changing operation. Ask a concise selectable question offering to keep the designated thread after the user opens it or to use another thread only if the user explicitly designates that thread. After confirmation, run a fresh read-only `probe` before continuing. Never auto-select a replacement thread, write Codex state directly, use foreground GUI control, or loop retries around the missing owner.

## Safety contract

- Require Windows x86-64, an absolute `--hermes-home`, a simple `--profile`, and an explicit absolute `--desktop-codex-home` (the Codex user-state directory containing `state_5.sqlite`, normally `%USERPROFILE%\\.codex`) on every invocation.
- Run `scripts/doctor.py --offline` after bootstrap and before controller use. Run online doctor checks before the first live operation after a Desktop upgrade.
- Treat `send`, `steer`, and `interrupt` as state-changing operations. Never retry an uncertain send automatically. The controller may make exactly one fresh-connection recovery only after an explicit IPC `no-client-found` rejection: that response proves the addressed Desktop client no longer existed and therefore could not have created a turn.
- After every confirmed `send` for a nontrivial execution task, immediately start exactly one tracked background waiter: run `desktop_controller.py ... wait --job JOB --timeout SECONDS` through `terminal(background=True, notify_on_complete=True)`. The controller takes only explicit absolute arguments and does not need a shell working directory: omit the `terminal` `workdir` field for this waiter. This prevents malformed or copy/paste-contaminated workdir values (including `\r`) from blocking its launch. A waiter timeout is a review gate, not task failure: after the waiter exits, inspect the job once with `status` and check for missing startup, approval waits, direction drift, or a need to steer. If that same job is still legitimately `running`, immediately start one replacement waiter with a task-appropriate timeout. Never re-send the task, never allow two waiters to coexist, and never use `process(wait)` to block the conversation. When the job reaches terminal state, independently verify any reported local/remote artifacts and synchronize newly created non-rebuildable material before dispatching another task.
- A controller `wait` observes the Codex Desktop turn only. If that turn launches a remote or detached child process, require its PID, progress path and completion markers in the returned task receipt. For an expected runtime above five minutes, instruct Codex to establish a single read-only remote monitor with a first snapshot by five minutes and snapshots every ten minutes thereafter (PID, progress, rate, CPU/GPU, disk, errors, terminal marker). The primary agent must also start an independent read-only verifier plus a five-minute delivery alarm; a completed/timed-out Codex turn is never proof that its remote child completed or failed, and Codex monitoring never replaces the primary agent's user-facing progress report.
- After a Desktop build or database migration changes, permit only structural checks and existing-job reads until `certify` succeeds on an explicitly designated test thread.
- Treat `certify` as a state-changing maintenance operation. It sends test turns, changes and restores model settings, steers one turn, and interrupts one turn on that exact test thread. Never choose a thread automatically.
- Certification defaults portably to model `gpt-5.6-sol` and reasoning effort `low`; an explicit user choice may override either with `certify --model MODEL --effort EFFORT`. Only the test-thread ID is installation/profile-local and must always be user-designated. Confirm that thread exists, is unarchived, and is idle before applying certification settings. If it is missing or not open, ask a selectable user question and never select a replacement automatically.
- **Upgrade recovery:** run `doctor.py --offline`, then the online doctor after a Desktop build/schema or migration warning. If it reports `structurally-compatible` with stale certification, use the already user-designated working/test thread only when the user explicitly authorizes automatic continuation or names that thread; run `certify --thread ID`, then rerun online doctor and `probe` before the next `send`. Do not bypass certification, retry a blocked send, or substitute foreground UI control.
- Keep generated jobs and temporary files below the selected profile's Skill data directory. Queue ledgers and immutable terminal history instead use the shared controller sidecar outside Codex home, so profiles cannot reserve the same thread independently.
- Queue enqueue requires ordinary valid profile certification plus the exact tested Desktop build/hash and queue protocol in `references/native-queue.md`. Adoption requires independently verified empty visible queue and exclusive controller management: no manual queue edits or other producers. One pending/unknown slot per canonical home/thread; never retry uncertain enqueue or delete its ledger. There is no cancel/reset support.
- Do not fall back to global `PATH`, `~/.codex`, Hermes configuration, PowerShell profiles, or ambient credentials.

## Commands

Set the common arguments explicitly:

```powershell
$Controller = '<skill>\scripts\desktop_controller.py'
$Common = @('--hermes-home', '<absolute-hermes-home>', '--profile', 'default', '--desktop-codex-home', '<absolute-codex-home>')
python $Controller @Common probe --thread <thread-id>
```

Use these subcommands:

- `probe --thread ID`: verify that the visible Desktop owns the thread.
- `send --thread ID --prompt TEXT [--model MODEL --effort EFFORT]`: update explicit thread settings first, then start a turn and return a job.
- `status --job JOB [--reconcile-turn TURN]`: read rollout state. For uncertain submissions, report candidates and require an exact turn ID before persisting reconciliation.
- `wait --job JOB --timeout SECONDS`: perform bounded Windows rollout monitoring until terminal state.
- `steer --job JOB --prompt TEXT [--model MODEL --effort EFFORT]`: steer the exact active turn.
- `interrupt --job JOB`: interrupt the exact active turn.
- `queue enqueue --thread ID --prompt TEXT [--adopt-empty-exclusive]`: submit one native follow-up without steering the current turn. Busy work finishes before native follow-up execution; idle execution is allowed. First use requires explicit empty/exclusive adoption; proven release permits reuse without re-adoption.
- `queue status --thread ID [--observe]`: reconcile exact persisted native client ID to running/terminal turn evidence and archive terminal proof before releasing the slot. Default status is local and available without certification; `--observe` adds gated read-only IPC. Queue IDs are not job IDs: use bounded background status monitoring, not `wait --job` with a queue ID. Missing/ambiguous evidence remains unknown/reserved.
- `certify --thread ID [--model MODEL] [--effort EFFORT] [--timeout SECONDS]`: apply the portable `gpt-5.6-sol`/`low` defaults unless explicitly overridden, then run the complete compatibility test on the user-designated thread and write a build-bound local receipt only after every check passes.

## References

- Read `references/compatibility.md` when Desktop, Node, or the state schema changes.
- Read `references/protocol.md` when debugging IPC or rollout events.
- Read `references/security.md` before changing paths, subprocess environments, job reconciliation, or dependency bootstrap behavior.
- Read `references/native-queue.md` and `references/queue-lifecycle.md` before queue adoption, enqueue, monitoring or acceptance. The legacy `--acceptance-test` label bypasses no gate.
- Treat `references/dependencies.lock.json` as the only dependency source of truth.

Protocol incompatibility, missing required database structure, stale certification, ambiguous uncertain jobs, and failed setting restoration must fail closed.
