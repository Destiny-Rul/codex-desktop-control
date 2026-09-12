# Codex Desktop Control certification status

- Skill version: `0.3.13`
- Live certification: passed at `2026-09-12T10:05:45.561311+00:00` (research profile)
- Target Desktop build: `26.908.4834.0`

Settings IPC now explicitly uses version 2 and requires `applied: true` before
continuing. It updates next-turn settings, not active-turn permissions.
The plain text `text_elements: []` rendering fix remains in place.

Offline settings-v2, protocol, owner recovery and certification settings tests
passed. A backend acknowledgement alone is not UI acceptance: live validation
must inspect actual test-window Desktop logs for renderer error boundaries.

Live send/wait/status, settings round-trip and restoration, same-turn steer,
exact interrupt and final probe passed. Post-certification online doctor
reported certified with writes enabled. The inspected certification window
contained 95 log lines, including 42 test-thread lines, with no matching React
error boundary, undefined-property error, EPIPE or crash marker. This is log
acceptance, not a claim of independently observed visual UI health.

Certification receipts are profile-local runtime data. Never copy them between
profiles or publish them. Certification uses only a user-designated test thread.
