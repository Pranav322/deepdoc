# 02: Fetch parked work — import evidence + Go/PHP call edges + Python inheritance

**What to build:** Go repos get function-level call graphs (resolving cross-package calls via import evidence). PHP/Laravel repos get call graphs (resolving `Class::method()` static calls, `new Class()` instantiation edges). Python repos get import-evidence-gated call-site disambiguation (ambiguous names resolve to the imported file, not a guess) and cross-file class inheritance walking. Previously, Go and PHP produced zero call edges, silently degrading to heuristic-only planning.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Go: `pkg.Func()` calls resolve to the imported package's function
- [ ] Go: receiver-method calls are marked unresolved (no guess)
- [ ] PHP: `Class::staticMethod()` calls resolve via `use` imports
- [ ] PHP: `$obj->method()` calls are marked unresolved
- [ ] Python: ambiguous bare-name calls resolve only when import evidence exists
- [ ] Python: aliased imports (`from x import y as z`) resolve correctly
- [ ] Python: re-export chains resolve to the defining file
- [ ] Python: circular imports don't hang
- [ ] Python: member calls (`obj.method()`) on imported classes resolve into the class's line range
- [ ] All existing call-graph tests pass unchanged