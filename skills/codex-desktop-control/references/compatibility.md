# Compatibility

This release is fail-closed but does not equate a UI bundle hash change with a protocol break. It requires Windows x86-64, Python 3.11 or newer, the pinned private Node archive, an official Codex Desktop MSIX install path, and the required `state_5.sqlite` structure.

## Compatibility levels

v0.3.14 targets settings-method v2, as observed in Desktop 26.908.4834.0. Older settings-v1 builds remain fail-closed; the historical reference build below is audit evidence, not a supported-version promise. IPC success alone does not prove UI health: live acceptance must check actual test-window Desktop logs for React error boundaries and verify the visible test-thread UI where necessary.

1. **Incompatible.** A required IPC anchor or method version is missing, multiple distinct Desktop builds are running, the executable is outside the official package path, a required database column is missing, a migration failed, or `PRAGMA quick_check` fails. No live Desktop operation is allowed.
2. **Structurally compatible.** The current build satisfies the protocol contract and database requirements, but no exact local certification receipt matches it. `probe`, `status`, and `wait` remain available; `send`, `steer`, and `interrupt` are blocked.
3. **Certified.** `certify` completed on an explicitly designated test thread and its receipt exactly matches the current Skill version, protocol contract, Desktop version, executable hash, protocol-payload hash, protocol fingerprint, migration count, and migration fingerprint. Ordinary write commands are available. Queue enqueue additionally requires Desktop 26.908.9136.0, the exact app.asar SHA-256 and setter-v1/broadcast-v2 contract pinned in `native-queue.md`, exclusive management and safe slot state; no broader queue builds are certified. Local queue status remains available without certification.

The full `ChatGPT.exe` and `app.asar` hashes remain build identity and audit evidence. They do not independently prove incompatibility. A new database migration is also drift rather than an automatic protocol failure when all migrations succeeded and the required structure remains present; it invalidates the prior receipt and requires recertification.

## Automatic certification

Run `certify --thread ID` only on a thread explicitly reserved for compatibility testing. Certification first applies and verifies the portable `gpt-5.6-sol`/`low` defaults, or explicit `--model` and `--effort` overrides; those applied settings become the certification originals. It then performs owner discovery, send/wait/status, a model-and-effort settings round trip, same-turn steer, exact-turn interrupt, final owner discovery, and final settings restoration. Any mismatch removes the receipt. Failure cleanup attempts to interrupt only exact turns acknowledged as created by that certification and restore the verified certification originals.

The reference build is Codex Desktop 26.803.10989.0. Its hashes and protocol fingerprint are retained in `dependencies.lock.json` as audit evidence, not as a permanent version allowlist.

Offline doctor performs no process launch, pipe connection, database write, network request, or dependency installation. It reports `structurally-compatible` or `certified` and whether write capabilities are enabled. Online doctor may additionally perform one read-only owner probe when a thread is supplied.
