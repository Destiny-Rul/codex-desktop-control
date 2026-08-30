# Codex Desktop Control certification status

- Skill version: `0.3.8`
- Last certified Codex Desktop build: `26.825.5331.0`
- Certified at: `2026-08-30T09:14:25.697918+00:00`
- Certification scope: Windows x86-64, profile-local receipt

## Status

v0.3.8 passed live Codex Desktop certification on the designated test thread.
The certified flow covered owner discovery, send/wait/status readback, settings
round-trip and restoration, same-turn steer, exact-turn interrupt, and a final
owner probe. Online doctor independently read the profile-local receipt back as
`compatibility_level: certified` with `write_capabilities_enabled: true`.

Certification receipts are machine-, profile-, skill-version-, Desktop-build-,
protocol-, and schema-specific. They are runtime data and are never published
or copied between devices.
