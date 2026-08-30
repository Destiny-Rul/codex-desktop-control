# Security and isolation

- Discover an owner through `thread-owner-discovery` before a live operation. A `no-client-found` response means no current owner and must fail closed; only an explicit `no-handler-for-request` from an older Desktop may use the settled follower-broadcast fallback.
- Resolve Skill data only from an explicit absolute Hermes home and validated profile name. Keep it below `skill-data/codex-desktop-control/profiles/<profile>`.
- Resolve Desktop state only from explicit `--desktop-codex-home`; never derive it from the user home.
- Invoke Node only by its absolute private path validated against `dependencies.lock.json` and the bootstrap install manifest.
- Construct subprocess environments from a small operating-system allowlist. Do not inherit API keys, proxy credentials, `PATH`, Python settings, Codex settings, or Hermes settings.
- Store only prompt hashes in jobs.
- Use atomic file replacement. Reject path separators in job IDs and profiles.
- Never retry an uncertain send. An explicit IPC `no-client-found` response is not uncertain: the addressed Desktop client has confirmed absent, so the controller may make one fresh-connection recovery. `status` may display candidate turn IDs; persist reconciliation only with an explicit exact candidate.
- Store the certification receipt below the selected profile runtime. Bind it to the exact Skill, protocol contract, Desktop build, and database migration identity; never copy it between profiles or machines.
- Run `certify` only with an explicitly supplied dedicated test thread. It must never enumerate, select, or switch to another thread.
- Before certification, require that test thread to be unarchived and idle. Apply and verify the portable `gpt-5.6-sol`/`low` defaults or explicit user overrides before testing; those verified values become the certification originals. On failure, remove the receipt, attempt to interrupt only the test thread's exact active turn, and restore the certification originals rather than the settings that preceded `certify`. A cleanup failure must never enable write capabilities.
- Do not package or copy binaries, runtime data, databases, rollouts, jobs, browser data, config, auth, or audit records.
- Bootstrap resets the private runtime DACL before granting only the current user, SYSTEM, and Administrators; it fails if any other principal remains. It writes only to the chosen profile Skill data and never changes PATH, registry, Hermes configuration, PowerShell profiles, Codex configuration, or credentials.
