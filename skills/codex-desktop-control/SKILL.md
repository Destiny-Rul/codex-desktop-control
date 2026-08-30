---
name: codex-desktop-control
description: Safely control existing Codex Desktop tasks on Windows.
version: 0.3.9
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
- After obtaining the user's consent, Hermes may control one or multiple Codex Desktop threads that the user explicitly designates. Keep every operation scoped to those threads; never select a thread or expand the controlled set on the user's behalf.
- Write Codex task prompts primarily in English, request use of FastCtx once, and leave model and reasoning settings under user control. Do not set or change them unless the user explicitly requests it.
- Immediately after dispatch, start exactly one task-appropriate controller `wait` as a non-blocking background job. Hermes may continue working or communicating in parallel and may inspect progress or steer the active turn when needed, but must not start a duplicate waiter.
- Treat a wait timeout as a review gate, not as task failure: inspect current state, decide whether to keep waiting or steer, and communicate material progress.
- When Codex completes, Hermes independently reviews and accepts the returned artifacts. If rework is required, repeat the dispatch, single background wait, and independent acceptance cycle.
- When a user decision is unclear and would materially affect the result, ask a concise selectable question before dispatching that choice.
- If owner discovery reports `no-client-found` because a user-designated thread is not open or visible in Codex Desktop, stop before any state-changing operation. Ask a concise selectable question offering to keep the designated thread after the user opens it or to use another thread only if the user explicitly designates that thread. After confirmation, run a fresh read-only `probe` before continuing. Never auto-select a replacement thread, write Codex state directly, use foreground GUI control, or loop retries around the missing owner.

## Safety contract

- Require Windows x86-64, an absolute `--hermes-home`, a simple `--profile`, and an explicit absolute `--desktop-codex-home` (the Codex user-state directory containing `state_5.sqlite`, normally `%USERPROFILE%\\.codex`) on every invocation.
- Run `scripts/doctor.py --offline` after bootstrap and before controller use. Run online doctor checks before the first live operation after a Desktop upgrade.
- Treat `send`, `steer`, and `interrupt` as state-changing operations. Never retry an uncertain send automatically. The controller may make exactly one fresh-connection recovery only after an explicit IPC `no-client-found` rejection: that response proves the addressed Desktop client no longer existed and therefore could not have created a turn.
- After every confirmed `send` for a nontrivial execution task, immediately start exactly one tracked background waiter: run `desktop_controller.py ... wait --job JOB --timeout SECONDS` through `terminal(background=True, notify_on_complete=True)`. The controller takes only explicit absolute arguments and does not need a shell working directory: omit the `terminal` `workdir` field for this waiter. This prevents malformed or copy/paste-contaminated workdir values (including `\r`) from blocking its launch. When that waiter exits, read the job once with `status`, independently verify any reported local/remote artifacts, and synchronize the newly created non-rebuildable material before dispatching another task. Do not rely on the user to ask for status, and do not launch duplicate waiters for the same job.
- A controller `wait` observes the Codex Desktop turn only. If that turn launches a remote or detached child process, require its PID, progress path and completion markers in the returned task receipt. For an expected runtime above five minutes, instruct Codex to establish a single read-only remote monitor with a first snapshot by five minutes and snapshots every ten minutes thereafter (PID, progress, rate, CPU/GPU, disk, errors, terminal marker). The primary agent must also start an independent read-only verifier plus a five-minute delivery alarm; a completed/timed-out Codex turn is never proof that its remote child completed or failed, and Codex monitoring never replaces the primary agent's user-facing progress report.
- After a Desktop build or database migration changes, permit only structural checks and existing-job reads until `certify` succeeds on an explicitly designated test thread.
- Treat `certify` as a state-changing maintenance operation. It sends test turns, changes and restores model settings, steers one turn, and interrupts one turn on that exact test thread. Never choose a thread automatically.
- Test-thread IDs, models, and reasoning settings are local to each user's Codex Desktop installation and Hermes profile. Never ship, infer, or reuse them as portable defaults; require the user to designate the thread and preserve that thread's user-controlled settings.
- **Upgrade recovery:** run `doctor.py --offline`, then the online doctor after a Desktop build/schema or migration warning. If it reports `structurally-compatible` with stale certification, use the already user-designated working/test thread only when the user explicitly authorizes automatic continuation or names that thread; run `certify --thread ID`, then rerun online doctor and `probe` before the next `send`. Do not bypass certification, retry a blocked send, or substitute foreground UI control.
- Keep generated jobs and temporary files below the selected profile's Skill data directory.
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
- `certify --thread ID [--timeout SECONDS]`: run the complete compatibility test on one explicitly designated test thread and write a build-bound local receipt only after every check passes.

## References

- Read `references/compatibility.md` when Desktop, Node, or the state schema changes.
- Read `references/protocol.md` when debugging IPC or rollout events.
- Read `references/security.md` before changing paths, subprocess environments, job reconciliation, or dependency bootstrap behavior.
- Treat `references/dependencies.lock.json` as the only dependency source of truth.

Protocol incompatibility, missing required database structure, stale certification, ambiguous uncertain jobs, and failed setting restoration must fail closed.
