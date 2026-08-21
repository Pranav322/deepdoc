# 07: End-to-end verification — generate docs for all 8 combos

**What to build:** A script or manual run that generates complete documentation for a representative repo in each of the 8 language+framework combinations. The output passes validation (no missing sections, no hallucinated paths, flow diagrams include runtime surfaces where applicable). This gates the entire feature: proves every combo works end-to-end.

**Blocked by:** 01, 02, 03, 04, 05, 06

**Status:** ready-for-agent

- [ ] Django fixture: generates with no validation failures
- [ ] DRF fixture: generates with no validation failures
- [ ] Falcon fixture: generates with no validation failures, runtime docs appear
- [ ] FastAPI fixture: generates with no validation failures, no mock-patch phantom endpoints, runtime docs appear
- [ ] Express fixture: generates with no validation failures
- [ ] Fastify fixture: generates with no validation failures
- [ ] NestJS fixture: generates with no validation failures, runtime docs appear
- [ ] Laravel fixture: generates with no validation failures
- [ ] Go fixture: generates with no validation failures, call graph edges produce topology clusters