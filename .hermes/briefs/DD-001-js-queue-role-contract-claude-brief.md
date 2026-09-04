# DD-001 Queue API Role Contracts

Work only in the isolated feature worktree. Verify all seams live.

Goal: finish the user-approved bounded JS/TS/Vue symbol binding. Do not use module provenance as if it were API capability.

Rules:
- BullMQ: only an imported/aliased `Worker` constructor is a consumer. `Queue` is producer-only; never infer `.process()`.
- Bull legacy: only a `new Bull(...)` instance can `.process()`.
- amqplib: only `connect()` -> connection -> `createChannel()` -> channel -> `.consume()`.
- Agenda: only an imported `Agenda` constructor -> instance -> `.define()`/`.every()`.
- Unsupported APIs and dynamic/cross-file flows fail closed.

TDD: add tests first for the two current false positives, the valid Bull legacy/Worker/AMQP/Agenda paths, aliases and shadowing. Correct existing BullMQ Queue.process fixtures. Run focused tests, full suite, compile, and the exact `/Users/apple/personal/delete/vscode` runtime probe. No `.hermes`, AGENTS, README, config, user-checkout, or `~/.claude` edits. Commit only scoped source/tests; do not merge or push.
