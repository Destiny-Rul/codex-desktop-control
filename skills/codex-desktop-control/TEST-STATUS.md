# Codex Desktop Control certification status

- Skill version: `0.3.10`
- Last certified Codex Desktop build: `26.825.6671.0`
- Certified at: `2026-08-30T16:09:06.290458+00:00`
- Certification scope: Windows x86-64, profile-local receipt

## Status

v0.3.10 passed live Codex Desktop certification. Certification portably
defaulted to model `gpt-5.6-sol` and reasoning effort `low` without explicit
CLI overrides, verified a temporary `medium` round trip, and restored `low`.
Either default may still be overridden by explicit user choice.

Only the test-thread ID is installation/profile-local and must be designated by
the user. A missing or not-open designated thread requires a selectable user
question; the controller and Hermes must not choose a replacement automatically.

Certification receipts are machine-, profile-, skill-version-, Desktop-build-,
protocol-, and schema-specific. They are runtime data and are never published
or copied between devices.
