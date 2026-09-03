# Codex Desktop Control certification status

- Skill version: `0.3.12`
- Last certified Codex Desktop build: `26.901.1978.0`
- Certified at: `2026-09-03T03:54:00.296716+00:00`
- Certification scope: Windows x86-64, profile-local receipt

## Status

v0.3.12 passed live Codex Desktop certification on build `26.901.1978.0` after
adding the required empty `text_elements` array to plain text turn input. The
unfixed request was accepted by the backend but caused the visible Desktop UI
to enter its React error boundary with `Cannot read properties of undefined
(reading 'length')`. Two focused send tests and the complete certification
sequence produced no matching error boundary after the fix.

Certification used the portable model `gpt-5.6-sol` and reasoning effort
`low`. Send/wait/status, settings round-trip and restoration, same-turn steer,
exact-turn interrupt, final owner discovery, and post-certification online
doctor checks passed. The Desktop main process remained stable and the test
thread settings were restored to `gpt-5.6-sol` / `low`.

Only the test-thread ID is installation/profile-local and must be designated by
the user. A missing or not-open designated thread requires a selectable user
question; the controller and Hermes must not choose a replacement automatically.

Certification receipts are machine-, profile-, skill-version-, Desktop-build-,
protocol-, and schema-specific. They are runtime data and are never published
or copied between devices.
