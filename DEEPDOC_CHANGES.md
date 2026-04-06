# DeepDoc Current State

This file is a current-state summary, not a historical session transcript.

## What DeepDoc Does

DeepDoc scans supported repos, plans bucketed documentation pages, generates grounded docs, builds a site, and optionally indexes the repo for chatbot retrieval.

## Current Architecture

- Scanning lives under `deepdoc/scanner/`
- Planning lives under `deepdoc/planner/`
- Generation lives under `deepdoc/generator/`
- Chatbot indexing and retrieval live under `deepdoc/chatbot/`
- Persistence and update logic live in `deepdoc/persistence_v2.py` and `deepdoc/smart_update_v2.py`

## Chatbot Current Behavior

- Indexes supported source files, artifacts/config, generated docs, repo-authored docs, and relationship chunks
- Uses hybrid retrieval: embedding search plus lexical exact-match search
- Expands linked files/docs through graph-neighbor retrieval
- Can stitch adjacent code windows for exact-match code hits
- Keeps live repo inspection limited to `/deep-research`

## Runtime Coverage Today

- Celery tasks, queues, producers, and beat schedules
- Django management commands, signal handlers, and Channels consumers
- Laravel jobs, events, listeners, and scheduler registrations
- JS/TS worker and queue patterns including agenda-style jobs
- Go background workers and scheduler patterns
- Socket.IO / websocket consumer patterns where statically visible

## Docs Quality Rules

- Generated pages are validated for sections, file grounding, route grounding, runtime grounding, config grounding, and integration grounding
- Invalid or degraded pages are surfaced in run-level quality reporting
- Quality output is persisted to `.deepdoc/generation_quality.json`

## Important Notes

- `README.md` and `AGENTS.md` are the primary maintained references for behavior and workflows
- Do not treat older references to `scan_v2.py`, `planner_v2.py`, or `generator_v2.py` as authoritative; the repo now uses package directories for those responsibilities
