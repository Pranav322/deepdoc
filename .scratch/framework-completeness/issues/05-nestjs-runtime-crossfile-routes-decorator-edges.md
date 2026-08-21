# 05: NestJS — add runtime discovery + cross-file route resolution + decorator call edges

**What to build:** Running `deepdoc generate` on NestJS repos produces correctly-composed API routes (resolving `@Controller('users')` prefixes across files), detects `@Cron()`/`@nestjs/bull` workers as runtime surfaces, and tracks `@UseGuards`/`@UseInterceptors` decorators as call-graph edges. Previously, NestJS routes could have incomplete paths, no runtime surfaces were detected, and the guard/interceptor/pipe layering was invisible to the call graph.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Cross-file controller prefix composition: `/users/:id` from `@Controller('users')` in users.controller.ts + `@Get(':id')` in a separate file resolves correctly
- [ ] `@Cron()` decorators detected as runtime schedulers
- [ ] `@InjectQueue()`/Bull queue consumers detected as runtime tasks
- [ ] `@UseGuards(AuthGuard)` → `AuthGuard` tracked as call-graph edge
- [ ] `@UseInterceptors(LoggingInterceptor)` → `LoggingInterceptor` tracked as call-graph edge
- [ ] Existing Express/Fastify detection unchanged
- [ ] New test fixture for NestJS runtime + cross-file routes + decorator edges