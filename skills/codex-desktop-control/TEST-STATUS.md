# Codex Desktop Control certification status

- Skill version: `0.3.11`
- Last certified Codex Desktop build: pending
- Certified at: pending
- Certification scope: Windows x86-64, profile-local receipt

## Status

v0.3.11 is pending live Codex Desktop certification. Certification portably
defaults to model `gpt-5.6-sol` and reasoning effort `low` without explicit
CLI overrides; either default may be overridden by explicit user choice.

Only the test-thread ID is installation/profile-local and must be designated by
the user. A missing or not-open designated thread requires a selectable user
question; the controller and Hermes must not choose a replacement automatically.

Certification receipts are machine-, profile-, skill-version-, Desktop-build-,
protocol-, and schema-specific. They are runtime data and are never published
or copied between devices.
