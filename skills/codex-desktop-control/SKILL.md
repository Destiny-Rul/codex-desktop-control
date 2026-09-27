---
name: codex-desktop-control
description: Safely control existing Codex Desktop tasks on Windows.
version: 0.3.19
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

### Roles

- Hermes plans stages, writes prompts, supervises execution, and makes the final acceptance decision. Codex executes. Treat every Codex report as a claim to verify, not as a result.
- Handle fast tasks directly. For necessary complex work, prefer Codex Desktop and minimize Hermes built-in subagents. Codex may decide on its own subagents without per-subagent authorization.

### Threads

- With the user's consent, control only the one or more threads the user explicitly designates. Never select a thread or expand the controlled set.
- Run a read-only `probe` first. If the thread has a live owner, dispatch through IPC in the background without UI interaction. Distinct designated threads may run concurrently.
- If `probe` reports `no-client-found`, stop before any state-changing operation and ask the user to open that exact thread in Codex Desktop. Do not open or switch it, infer the cause, pick another thread, retry in a loop, or substitute CLI/SDK/app-server execution: an external writer blocks Desktop from resuming the thread while it runs. After the user confirms, run a fresh `probe`; if ownership is still missing, stop and report.

### Dispatch contract

- Split complex work into meaningful, verifiable stages. Dispatch only the current stage; review it before the next. Do not fragment simple tasks.
- Every stage prompt must state, and must not be sent without:
  - **Goal**: the outcome of this stage.
  - **Context**: working directory, relevant files, and verified conclusions from earlier stages.
  - **Scope**: what may change, and explicitly forbidden actions (for example commit, push, install, live operations).
  - **Stop**: the boundary at which Codex must stop.
  - **Report**: changed files, exact commands run with their real output, and unresolved risks.
- Write prompts primarily in English as direct requests ("Please inspect...", "Please implement..."), not "The user needs...". Request FastCtx for file I/O once within each dispatched prompt. Leave model and reasoning settings unchanged unless the user explicitly asks.

### Adapt prompts to observed behavior

Rewrite the next prompt from what Codex actually did; do not resend a rigid template. Keep prompts precise and concise.

| Observed | Next prompt |
| --- | --- |
| No-op (empty reply or no changes) | Name the required concrete file or output and narrow the scope. |
| Scope overreach | Explicitly forbid the specific action that crossed the boundary. |
| Direction drift | Steer quoting the drifting statement, state the correction, restate Stop. |
| Vague report or unverifiable test claims | Require the exact commands and raw output. |
| Two unstable rounds in a row | Split into a smaller stage; never resend the same prompt. |

### Skeptical acceptance

- Verify evidence first: `git diff`, actual file contents, and key tests rerun by Hermes.
- Check each Codex claim; a claim without evidence counts as not done. Check for changes outside the stage scope.
- Record exactly one verdict per stage: **accepted**, **rework**, **no-op**, or **overreach**. For the last three, state the concrete findings and redispatch using the adaptation table.
- If accepted and the next dependent stage stays within the user's authorization, dispatch it without routine reconfirmation. Ask the user only for a material new decision or scope expansion.

### Execution control

- After each acknowledged dispatch, start exactly one non-blocking background waiter (see Safety contract). Set its timeout from the stage's expected duration. Continue working in parallel; never block on it with `process(wait)`.
- A timeout is a review checkpoint, not failure: inspect `status`, then choose one of continue waiting, steer, or interrupt.
- Steer only to correct direction or add a missing constraint, never to append new work.
- Interrupt only for clear overreach, a dangerous action, or confirmed wasted execution.
- When the user's intent within this Skill's Codex-control scope is unclear, or an ambiguity would materially affect a control, monitoring, or acceptance decision, call the Hermes `clarify` tool with selectable options instead of guessing.

## Safety contract

- Require Windows x86-64, an absolute `--hermes-home`, a simple `--profile`, and an explicit absolute `--desktop-codex-home` (the Codex user-state directory containing `state_5.sqlite`, normally `%USERPROFILE%\\.codex`) on every invocation.
- Run `scripts/doctor.py --offline` after bootstrap and before controller use. Run online doctor checks before the first live operation after a Desktop upgrade.
- Treat `send`, `steer`, and `interrupt` as state-changing operations. Never retry an uncertain send automatically. The controller may make exactly one fresh-connection recovery only after an explicit IPC `no-client-found` rejection: that response proves the addressed Desktop client no longer existed and therefore could not have created a turn.
- Waiter mechanics: after every acknowledged `send`, run `desktop_controller.py ... wait --job JOB --timeout SECONDS` through `terminal(background=True, notify_on_complete=True)`. Omit the `terminal` `workdir` field; the controller takes only explicit absolute arguments, and a contaminated workdir (including `\r`) would block launch. After the waiter exits, inspect the job once with `status`. If the same job is still `running`, start exactly one replacement waiter. Never re-send the task, never let two waiters coexist, and never block with `process(wait)`.
- A controller `wait` observes the Codex Desktop turn only. A completed turn is not proof that any detached or remote child process it launched has finished.
- After a Desktop build or database migration changes, permit only structural checks and existing-job reads until `certify` succeeds on an explicitly designated test thread.
- Treat `certify` as a state-changing maintenance operation. It sends test turns, changes and restores model settings, steers one turn, and interrupts one turn on that exact test thread. Never choose a thread automatically.
- Certification defaults portably to model `gpt-6-luna` and reasoning effort `low`; an explicit user choice may override either with `certify --model MODEL --effort EFFORT`. Only the test-thread ID is installation/profile-local and must always be user-designated. Confirm that thread exists, is unarchived, idle, and owned before applying certification settings. If any prerequisite is missing, stop and request a user decision; never select a replacement automatically.
- **Upgrade recovery:** run `doctor.py --offline`, then the online doctor after a Desktop build/schema or migration warning. If it reports `structurally-compatible` with stale certification, run `certify --thread ID` only on the user-designated test thread, never on a working thread, and only after the user authorizes it or has standing authorization for recertification; then rerun online doctor and `probe` before the next `send`. Do not bypass certification, retry a blocked send, or substitute another control surface.
- Keep generated jobs and temporary files below the selected profile's Skill data directory.
- A completed waiter/turn releases the active job, not necessarily the Desktop's loaded thread or its memory. Do not claim per-thread resource reclamation from a completed turn or elapsed time. Inactive-thread unsubscribe is conditional (three-hour TTL or pressure above the retained-owner cap, subject to keep-loaded conditions); read-only owner probes do not measure per-thread memory. Do not invoke undocumented unsubscribe/stop or kill a process as routine cleanup.
- Do not fall back to global `PATH`, `~/.codex`, Hermes configuration, PowerShell profiles, or ambient credentials.

## Commands

Set the common arguments explicitly:

```powershell
$Controller = '<skill>\scripts\desktop_controller.py'
$Common = @('--hermes-home', '<absolute-hermes-home>', '--profile', 'default', '--desktop-codex-home', '<absolute-codex-home>')
python $Controller @Common probe --thread <thread-id>
```

Use these subcommands:

- `probe --thread ID`: verify that Desktop owns the exact designated thread.
- `send --thread ID --prompt TEXT [--model MODEL --effort EFFORT]`: update explicit thread settings first, then start a turn and return a job.
- `status --job JOB [--reconcile-turn TURN]`: read rollout state. For uncertain submissions, report candidates and require an exact turn ID before persisting reconciliation.
- `wait --job JOB --timeout SECONDS`: perform bounded Windows rollout monitoring until terminal state.
- `steer --job JOB --prompt TEXT [--model MODEL --effort EFFORT]`: steer the exact active turn.
- `interrupt --job JOB`: interrupt the exact active turn.
- `certify --thread ID [--model MODEL] [--effort EFFORT] [--timeout SECONDS]`: apply the portable `gpt-6-luna`/`low` defaults unless explicitly overridden, then run the complete compatibility test on the user-designated thread and write a build-bound local receipt only after every check passes.

## References

- Read `references/compatibility.md` when Desktop, Node, or the state schema changes.
- Read `references/protocol.md` when debugging IPC or rollout events.
- Read `references/security.md` before changing paths, subprocess environments, job reconciliation, or dependency bootstrap behavior.
- Treat `references/dependencies.lock.json` as the only dependency source of truth.

Protocol incompatibility, missing required database structure, stale certification, ambiguous uncertain jobs, and failed setting restoration must fail closed.
