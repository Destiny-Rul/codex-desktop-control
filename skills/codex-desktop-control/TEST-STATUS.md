# Codex Desktop Control certification status

## Current

- Skill version: `0.3.20`
- v0.3.20 live certification: **passed** at `2026-10-09T12:19:20Z` on Desktop `26.1002.7124.0` (research profile) in a split layout (`--desktop-codex-home <codex-home>`, `--desktop-sqlite-home <codex-home>\sqlite`), 17.2 s, with `gpt-6-luna` / `low`. Send/wait/status, settings round-trip, same-turn steer, exact interrupt and final probe passed; online doctor reports `certified`, writes enabled, no issues. Certification-window Desktop logs (158 lines, 28 test-thread lines) had no error-boundary, undefined-property, TypeError, EPIPE or crash marker. The Skill version change and the receipt `desktop_layout` field invalidate earlier receipts; other profiles need bootstrap and certification.
- v0.3.20 adds optional `--desktop-sqlite-home` for Codex `sqlite_home` layouts (`state_5.sqlite` in `<codex-home>\sqlite`). Offline regressions cover database/rollout root separation, unchanged session-root and UNC guards, lock keys, receipt layout binding, and queue slot identity.
- v0.3.19 live certification (historical): **passed** on Desktop `26.924.2738.0` (research profile), 59.531 s, with `gpt-6-luna` / `low`. Send/wait/status, settings round-trip, same-turn steer, exact interrupt and final probe all passed; online doctor reports `certified`, writes enabled, no issues. The certification-window Desktop logs (5019 lines, 105 test-thread lines) contained no React error-boundary, undefined-property, TypeError, EPIPE or crash marker; 209 ResizeObserver warnings are reported separately.
- Portable certification default: `gpt-6-luna` / `low`
- Native queue: **disabled** in the CLI and the internal enqueue boundary. Historical code, ledgers and receipts are retained for later review.
- Certification receipts are profile-local runtime data. Never copy them between profiles or publish them. Certification uses only a user-designated test thread.

## Established behavior

- Owner-held designated threads accept background turns without UI interaction. Two threads ran concurrently: one completed while the other was still running (Desktop `26.924.1866.0`).
- A completed turn does not unload its thread. Both threads stayed owned through about 35 minutes of read-only observation (Desktop `26.924.2738.0`). Desktop logs later showed `inactive_thread_unsubscribed` about three hours after a resume. Per-thread memory attribution was not established.
- While an external CLI writer ran on a thread, Desktop's resume of that thread was rejected with `already has an active writer`. External writers are therefore not a supported fallback.
- Settings IPC uses version 2 and requires `applied: true`; it updates next-turn settings, not active-turn permissions. Plain text inputs carry `text_elements: []` to avoid a renderer crash.
- A backend acknowledgement alone is not UI acceptance. Live validation must inspect actual Desktop logs for renderer error boundaries. ResizeObserver warnings are reported separately and are not a functional failure.

## Certification history (historical only)

| Skill | Desktop | Result |
| --- | --- | --- |
| 0.3.18 | 26.924.1866.0 | passed `2026-09-26T08:09:01Z` (research) |
| 0.3.17 | 26.924.1866.0 | passed `2026-09-26T02:25:07Z` with `gpt-6-luna` / `low` (research); an earlier attempt hit an HTTP 422 model allowlist error |
| 0.3.16 | 26.915.4065.0, 26.917.8451.0 | passed (research), 97.031 s on the first build; used the previous certification model |
| 0.3.15 | 26.911.7940.0 (migration 55) | passed `2026-09-17T12:48:39Z` in 47.297 s (research) |

Earlier certifications are superseded by the rows above. Stage 1 concurrency and speed-up work measured a full certification of 40.953 s (send_settings 12.531 s, steer 21.797 s, interrupt 0.641 s) with no matching renderer errors.

## Queue history (disabled; historical only)

- On Desktop `26.908.9136.0` (2026-09-16), one trial and two repeated-use cycles passed. Each starter completed before its distinct follow-up (493 ms, 96 ms, 93 ms). `UserMessage.client_id` matched the queue item ID. A second enqueue was rejected before IPC, and slots released through exact terminal reconciliation.
- On Desktop `26.911.7940.0` (app.asar SHA-256 `74e7aaf2c112f84ef68a7846d10d1411403e72763f7e93fe046df2f264adf6e0`), one cycle passed. The follow-up turn `01a0af8b-2444-7540-845c-322c788d87c3` started 191 ms after the starter. An owner-change uncertainty was not retried; exact persisted evidence later mapped queue item `e16123b0-d2c2-4d8e-9b51-3cd55356914a`. Terminal receipt SHA-256 `53673b66a9aced42d019a8a39a323ff583fcd412424e6b8827319bec86f1cfbe`.
- These observations do not certify any other build or profile. See `references/queue-lifecycle.md`.
