# Compatibility

This release is fail-closed but does not equate a UI bundle hash change with a protocol break. It requires Windows x86-64, Python 3.11 or newer, the pinned private Node archive, an official Codex Desktop MSIX install path, and the required `state_5.sqlite` structure.

## Compatibility levels

1. **Incompatible.** A required IPC anchor or method version is missing, multiple distinct Desktop builds are running, the executable is outside the official package path, a required database column is missing, a migration failed, or `PRAGMA quick_check` fails. No live Desktop operation is allowed.
2. **Structurally compatible.** The current build satisfies the protocol contract and database requirements, but no exact local certification receipt matches it. `probe`, `status`, and `wait` remain available; `send`, `steer`, and `interrupt` are blocked.
3. **Certified.** `certify` completed on an explicitly designated test thread and its receipt exactly matches the current Skill version, protocol contract, Desktop version, executable hash, protocol-payload hash, protocol fingerprint, migration count, and migration fingerprint. All commands are available.

The full `ChatGPT.exe` and `app.asar` hashes remain build identity and audit evidence. They do not independently prove incompatibility. A new database migration is also drift rather than an automatic protocol failure when all migrations succeeded and the required structure remains present; it invalidates the prior receipt and requires recertification.

## Automatic certification

Run `certify --thread ID` only on a thread explicitly reserved for compatibility testing. It performs owner discovery, send/wait/status, a model-and-effort settings round trip, same-turn steer, exact-turn interrupt, final owner discovery, and final settings restoration. Any mismatch removes the receipt. Failure cleanup attempts to interrupt only that test thread's exact active turn and restore its original settings.

The reference build is Codex Desktop 26.803.10989.0. Its hashes and protocol fingerprint are retained in `dependencies.lock.json` as audit evidence, not as a permanent version allowlist.

Offline doctor performs no process launch, pipe connection, database write, network request, or dependency installation. It reports `structurally-compatible` or `certified` and whether write capabilities are enabled. Online doctor may additionally perform one read-only owner probe when a thread is supplied.
