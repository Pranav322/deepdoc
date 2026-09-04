# Handoff — DD-001/DD-002 Blocked for Architecture Decision

**Branch:** `fix/runtime-scan-stabilization`  
**Current head:** `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f`  
**Status:** clean, isolated, unmerged, **rejected by fresh independent review**.  
**Never do:** push, open PR, merge, modify main, or call the VS Code phase probes/canonical benchmark until a new design passes review and Pranav approves.

## Why we stopped direct patching

Fresh review batch `deleg_809597cb` found and Hermes reproduced a shared architecture problem after several prior narrow corrections:

1. 251 duplicate-name runtime tasks × 257 matching producers = 64,507 task checks.
2. Raw workflow regexes let JS comments/template literals/generic methods become producer evidence for real Python tasks.
3. Marker/extractor grammar drift loses valid whitespace-spelled dispatches.
4. Scheduler endpoint linking still sweeps every endpoint-owning file through every scheduler.
5. Laravel FQCN dispatches cannot link to short-name discovered tasks.
6. JS binder misses shadow forms (`var`, function/class expressions, TS import aliases) and safe member aliases.

Full details: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-final-review-round3-blockers.md`.

## Required user decision

Do not perform another independent micro-patch. Ask Pranav to choose whether Hermes should directly implement the recommended bounded architecture redesign, pause for a written design review, delegate redesign to Claude, or leave the branch rejected.

## Recommended design direction

A DeepDoc-owned evidence/linking layer:

- language-aware `DispatchEvidence` extraction (structural JS/TS/Vue; syntax-aware other languages);
- canonical target keys plus aliases, with ambiguity fail-closed instead of one spelling fanning out to every duplicate task;
- one evidence-indexed task/scheduler endpoint linker;
- scoped JS binder extensions for declaration kinds/var scope/member aliases;
- Laravel FQCN/short-name alias normalization with collision handling.

## Durable issue state

DD-001/DD-002 return to blocked. New P0 subissues DD-013–DD-017 cover the distinct confirmed architectural blockers. Endpoint publication boundary remains verified, but runtime DD-002 cannot close while raw JS workflow linking remains.
