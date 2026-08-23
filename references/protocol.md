# Protocol contract

## Desktop IPC

Use `\\.\pipe\codex-ipc` with little-endian 32-bit length-prefixed UTF-8 JSON frames. Reject frames above 32 MiB.

Initialize as `clientType: farfield`, then use `thread-owner-discovery` with `hostId: "local"` and the conversation ID. Target its returned `handledByClientId`; it is the authoritative thread owner. `thread-stream-following-changed` is only a compatibility fallback after a short settle window, because its source merely reports a follower relationship and may not own the thread.

For a send with model or effort overrides, issue operations in this exact order:

1. `thread-follower-update-thread-settings` with `conversationId` and `threadSettings`.
2. Require a successful response.
3. For a new turn, call `thread-follower-start-turn` **version 2** with `conversationId` and `turnStart: {request, context}`. The request contains `threadId`, input, model and effort; the context contains the attachment arrays and `inheritThreadSettings: true`. Require the acknowledged `turn.id`.
4. For guidance on an active turn, call `thread-follower-steer-turn` with the exact conversation and text input; require its `turnId` to equal the parent job's active turn.
5. If either acknowledgement is absent or mismatched, persist the outcome as uncertain and do not retry automatically. An explicit IPC `no-client-found` response from a targeted request is different: it is a negative acknowledgement that the targeted client did not exist. The controller may reconnect once, rediscover the owner, and resend the same operation. A `no-client-found` response from `thread-owner-discovery` means there is no current owner and must fail closed; it must not fall back to follower broadcasts. Any second targeted `no-client-found`, timeout, malformed response, or other error remains fail-closed.

Use `thread-follower-interrupt-turn` version 4 with `expectedTurnId` for interrupt. Never infer a replacement turn after an interrupt mismatch.

The protocol scanner reads the installed `app.asar` and verifies the locked IPC anchors and method-version table. It computes a semantic protocol fingerprint separately from the full payload hash. Missing or ambiguous method versions are incompatible; unrelated UI or packaging bytes may change without changing the semantic fingerprint.

The settings-only operation calls `thread-follower-update-thread-settings` and starts no turn. Certification uses it only to restore and verify the test thread's original model and effort.

## Rollout state

Recognize `task_started`, `agent_message`, `task_complete`, `task_failed`, `turn_aborted`, and `turn_interrupted`. Scope all completion events to the acknowledged or explicitly reconciled turn ID. Ignore an incomplete final JSONL line; reject malformed complete records, lifecycle events without turn IDs, and rollout truncation below the job baseline. `wait` must use bounded Windows `ReadDirectoryChangesW` notification, call `CancelIoEx`, and wait for overlapped cancellation completion before releasing its buffer and handles; it must not poll the rollout in a sleep loop.

Certification must wait for the acknowledged turn to enter `running` before steering or interrupting. It must require same-turn steer acknowledgement and exact `interruptedTurnId` acknowledgement.
