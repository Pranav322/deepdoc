# DD-001 Queue API Role Contract Gap

Reviewed `4bb3b013` on `fix/runtime-scan-stabilization`.

The binding resolver proves module provenance but not API role. Deterministic repro showed two false jobs:

- `import { Queue } from "bullmq"; new Queue(...).process(...)`
- `import amqplib from "amqplib"; amqplib.createCodec().consume(...)`

Both must be ignored. A legacy `Bull` queue `.process()` remains valid.

Cause: `module-derived value` is too broad. Required correction: typed intrafile roles and only explicit role transitions:
`BullMQ Worker`, `Bull legacy Queue`, `AMQP connection/channel`, and `Agenda instance`. Unmapped flows fail closed. This is universal JS/TS/Vue behavior, not a VS Code exception.
