# Codex Desktop Control

A Windows-only Hermes Agent skill for safely controlling a specific task that
is already open in Codex Desktop. It uses Codex Desktop's structured local IPC,
keeps task progress visible in the Desktop UI, and fails closed when ownership,
protocol, schema, or certification cannot be verified.

> [!WARNING]
> This is an independent community project. It is not affiliated with or
> endorsed by OpenAI, Codex, Nous Research, or Hermes Agent. Codex Desktop's
> private IPC and state schema can change without notice. Every Desktop build
> or schema change disables writes until a profile-local certification passes.

## What it supports

- Probe whether the visible Codex Desktop client owns an exact thread.
- Send a task to an explicitly named thread.
- Wait for and inspect the exact turn without polling sleeps.
- Steer or interrupt the exact active turn.
- Certify probe, send/wait/status, settings restoration, same-turn steer, and
  exact interrupt against one user-designated test thread.
- Keep jobs, dependencies, and certification receipts isolated per Hermes
  profile.

It does **not** select a thread automatically, bypass Codex permissions, copy
credentials, or treat an observer timeout as task failure.

## Requirements

- Windows 11 x86-64
- Python 3.11 or newer
- Codex Desktop installed and running
- Hermes Agent
- A Codex state directory containing `state_5.sqlite` (normally
  `%USERPROFILE%\.codex`)

The bootstrap downloads a pinned Node.js runtime from `nodejs.org`, verifies the
archive and executable SHA-256 values, and installs it inside the selected
Hermes profile. No Node binary, Codex database, rollout, credential, job, or
certification receipt is stored in this repository or its release ZIP.

## Install with Hermes

Inspect the community skill before installing it:

```powershell
hermes skills inspect Destiny-Rul/CodexAgentControl/skills/codex-desktop-control
```

Install it into the active Hermes profile:

```powershell
hermes skills install Destiny-Rul/CodexAgentControl/skills/codex-desktop-control
```

Installed skills are security-scanned by Hermes. Start a new session after
installation so the skill catalog is refreshed.

## Bootstrap and verify

Resolve the active Hermes home from its config path rather than assuming a
machine-specific directory:

```powershell
$HermesHome = Split-Path -Parent (hermes config path)
$Skill = Join-Path $HermesHome 'skills\codex-desktop-control'
$CodexHome = Join-Path $env:USERPROFILE '.codex'
$Profile = 'default'

powershell -NoProfile -ExecutionPolicy Bypass -File `
  (Join-Path $Skill 'scripts\bootstrap.ps1') `
  -HermesHome $HermesHome `
  -Profile $Profile

python (Join-Path $Skill 'scripts\doctor.py') `
  --offline `
  --hermes-home $HermesHome `
  --profile $Profile `
  --desktop-codex-home $CodexHome
```

For a named Hermes profile, use its config path and the same profile name:

```powershell
$Profile = 'research'
$HermesHome = Split-Path -Parent (hermes -p $Profile config path)
```

If Windows PowerShell 5.1 loads an incompatible PowerShell 7
`Microsoft.PowerShell.Security` module, temporarily limit `PSModulePath` for the
bootstrap process to the Windows PowerShell module directories. Do not change
the global environment.

## Certify write operations

Certification is a state-changing maintenance test. It sends test turns,
changes and restores thread settings, steers one turn, and interrupts one turn.
Use only a dedicated, idle, explicitly selected test thread:

```powershell
$Controller = Join-Path $Skill 'scripts\desktop_controller.py'
$Thread = '<dedicated-test-thread-id>'

python $Controller `
  --hermes-home $HermesHome `
  --profile $Profile `
  --desktop-codex-home $CodexHome `
  certify --thread $Thread --timeout 240

python (Join-Path $Skill 'scripts\doctor.py') `
  --hermes-home $HermesHome `
  --profile $Profile `
  --desktop-codex-home $CodexHome `
  --thread $Thread
```

A successful online doctor must report:

```text
compatibility_level: certified
write_capabilities_enabled: true
```

Never copy `desktop-build.json` between profiles, devices, skill versions, or
Desktop builds.

## Controller commands

Every invocation requires explicit absolute paths and an exact thread or job:

```text
probe --thread ID
send --thread ID --prompt TEXT [--model MODEL --effort EFFORT]
status --job JOB [--reconcile-turn TURN]
wait --job JOB --timeout SECONDS
steer --job JOB --prompt TEXT [--model MODEL --effort EFFORT]
interrupt --job JOB
certify --thread ID [--timeout SECONDS]
```

Read [`skills/codex-desktop-control/SKILL.md`](skills/codex-desktop-control/SKILL.md)
for the complete safety contract and waiter rules.

## Update

Check and install upstream updates through Hermes:

```powershell
hermes skills check
hermes skills update codex-desktop-control
```

After an update, rerun bootstrap and the offline doctor. A skill-version,
Desktop-build, protocol, or schema identity change requires recertification
before write operations are enabled.

## Development and verification

```powershell
python tools\verify_package.py
python skills\codex-desktop-control\scripts\test_protocol_v2.py
python skills\codex-desktop-control\scripts\test_owner_recovery.py
python tools\build_release.py
```

GitHub Actions runs the package verifier, Python compilation, and regression
tests on `windows-latest`. Live Desktop certification remains a manual release
gate because hosted CI does not own a real Codex Desktop test thread.

## Security and privacy

- Prompts are represented by hashes in persisted job records.
- Runtime data stays below the selected Hermes profile's skill-data directory.
- Subprocesses receive a restricted environment and an absolute pinned Node
  path.
- Uncertain sends are never retried automatically.
- Release artifacts exclude runtime state, receipts, jobs, databases,
  credentials, browser data, and downloaded binaries.

See [`references/security.md`](skills/codex-desktop-control/references/security.md)
for the detailed isolation contract.

## License

MIT — see [`LICENSE`](LICENSE).
