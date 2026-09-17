# Codex Desktop Control certification status

- Skill version: `0.3.15`
- Reusable queue live acceptance: passed on the current pinned build
- v0.3.15 live certification: passed at `2026-09-17T12:48:39.499574+00:00` (research profile)
- Queue target Desktop build: `26.911.7940.0` (exact app.asar hash pinned)

Stage 1 independent live acceptance was reported by the user at
`2026-09-15T08:50:10.250265+00:00`: total 40.953s, send_settings 12.531s,
steer 21.797s, interrupt 0.641s; 69 Desktop log lines including 31 test-thread
lines had no matching renderer errors. This is historical evidence, not live
certification of the changed queue code. No live operations were run for queue
initial implementation. The one native queue trial on 2026-09-16 functionally
passed: persisted UserMessage.client_id exactly correlated to the completed
distinct follow-up turn. ResizeObserver warnings occurred before and during that
trial and are reported separately, not treated as proof of a queue failure or
a generic zero-console-errors functional prerequisite.

On 2026-09-16, two further busy enqueue cycles passed independent review of
original rollout ordering, both exact UserMessage.client_id mappings and all
three immutable ledger history hashes. Each starter completed before its distinct
follow-up began (96ms and 93ms respectively). Each slot released through exact
terminal reconciliation; second enqueue rejected before IPC, history remained
unchanged and settings were preserved. The repeated-use window contained 126
Desktop log lines (44 test-thread lines), with no ResizeObserver or matching new
renderer errors. These bounded observations do not certify broader builds or
another profile. See `references/queue-lifecycle.md` for the acceptance procedure.

Hermes independently verified ordinary v0.3.15 certification on Desktop
26.911.7940.0, migration 55, with the ordinary protocol fingerprint unchanged.
It also verified
setter v1, broadcast v2, the acceptFromFollower replacement path and native
text_elements path remain present in app.asar SHA-256
`74e7aaf2c112f84ef68a7846d10d1411403e72763f7e93fe046df2f264adf6e0`.
The complete certification passed send/wait/status, settings round-trip and
restoration, same-turn steer, exact interrupt and final probe in 47.297 seconds.

One current-build queue cycle also passed. The native submission reported an
owner-change uncertainty, so it was not retried and no setter acknowledgement
was claimed. Exact persisted evidence later mapped queue item
`e16123b0-d2c2-4d8e-9b51-3cd55356914a` to distinct turn
`01a0af8b-2444-7540-845c-322c788d87c3` through `UserMessage.client_id`; the
starter completed 191ms before that turn started, the exact turn completed, and
terminal receipt SHA-256
`53673b66a9aced42d019a8a39a323ff583fcd412424e6b8827319bec86f1cfbe`
was archived before the slot released. Prior receipt hashes and settings were
unchanged. The bounded Desktop window contained no matching React/error-boundary,
TypeError, undefined-property, EPIPE or crash marker; ResizeObserver warnings are
reported separately and are not a generic functional prerequisite. Certification
remains profile-local and must never be transplanted.

Settings IPC now explicitly uses version 2 and requires `applied: true` before
continuing. It updates next-turn settings, not active-turn permissions.
The plain text `text_elements: []` rendering fix remains in place.

Offline settings-v2, protocol, owner recovery and certification settings tests
passed. A backend acknowledgement alone is not UI acceptance: live validation
must inspect actual test-window Desktop logs for renderer error boundaries.

Historical (pre-Stage 1) live send/wait/status, settings round-trip and restoration, same-turn steer,
exact interrupt and final probe passed. Post-certification online doctor
reported certified with writes enabled. The inspected certification window
contained 95 log lines, including 42 test-thread lines, with no matching React
error boundary, undefined-property error, EPIPE or crash marker. This is log
acceptance, not a claim of independently observed visual UI health.

Certification receipts are profile-local runtime data. Never copy them between
profiles or publish them. Certification uses only a user-designated test thread.
