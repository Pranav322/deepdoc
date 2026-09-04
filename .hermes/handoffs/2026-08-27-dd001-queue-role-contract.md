# Handoff — DD-001 Queue Role Contracts

User chose bounded JS/TS/Vue symbol binding for all repositories; VS Code is only the stress benchmark.

Current local branch: `fix/runtime-scan-stabilization`; latest reviewed commit `4bb3b013`. It is not merge-ready: its binding tracks a module but not a package API role. It falsely reports BullMQ `Queue.process()` and unrelated values derived from `amqplib` as consumers.

Authorized next scope: typed intrafile roles only:
- BullMQ `Worker` constructor -> consumer
- Bull legacy queue -> `.process()` consumer
- AMQP `connect` -> `createChannel` -> `.consume()`
- Agenda constructor -> `.define()`/`.every()`
- unknown/dynamic/cross-file flow -> no claim

No merge or PR. Exact user benchmark path: `/Users/apple/personal/delete/vscode`.
