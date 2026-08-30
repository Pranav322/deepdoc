# DeepDoc Benchmark Report

**Date**: 2026-08-29T13:31:37.089713
**Total**: 16
**Passed**: 16
**Failed**: 0
**Pass rate**: 100%

---

## PASS A/broken-imports (0.0s)
**Metrics:**
- imports: 3
- kind:src/main.py: product
- overall_parse_rate: 1.0

## PASS A/copy-paste-trap (0.0s)
**Metrics:**
- files: 3
- kind:src/auth.py: product
- kind:src/payment.py: product
- kind:src/storage.py: product
- overall_parse_rate: 1.0
- symbols: 6

## PASS A/fixture-trap (0.0s)
**Metrics:**
- kind:tests/fixtures/payment_api.py: fixture
- overall_parse_rate: 1.0
- route_records: 0
- status:tests/fixtures/payment_api.py: full

## PASS A/generated-trap (0.0s)
**Metrics:**
- kind:src/generated/models.generated.ts: generated
- overall_parse_rate: 1.0
- status:src/generated/models.generated.ts: full

## PASS A/name-collision (0.0s)
**Metrics:**
- files: 5
- kind:src/notification_service.py: product
- kind:src/order_service.py: product
- kind:src/payment_service.py: product
- kind:src/product_service.py: product
- kind:src/user_service.py: product
- overall_parse_rate: 1.0
- symbols: 5

## PASS A/polyglot-small (0.0s)
**Metrics:**
- files: 4
- kind:src/config.foo: product
- kind:src/legacy.rb: product
- kind:src/main.py: product
- kind:src/server.ts: product
- parsed_files: 2
- status:src/config.foo: inventory_only
- status:src/legacy.rb: inventory_only
- status:src/main.py: full
- status:src/server.ts: full
- unsupported_languages: ['Ruby', 'foo']

## PASS A/test-file-trap (0.0s)
**Metrics:**
- kind:tests/app/controllers.py: test
- overall_parse_rate: 1.0
- route_records: 0
- status:tests/app/controllers.py: full

## PASS A/unknown-foo (0.0s)
**Metrics:**
- files: 1
- status:src/README: unknown

## PASS B/django_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['django']
- parsed_files: 1
- route_records: 8

## PASS B/express_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['express']
- parsed_files: 1
- route_records: 3

## PASS B/falcon_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['falcon']
- parsed_files: 2
- route_records: 3

## PASS B/fastify_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['fastify']
- parsed_files: 1
- route_records: 2

## PASS B/go_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['gin', 'go']
- parsed_files: 1
- route_records: 3

## PASS B/java_app (0.0s)
**Warnings:**
- Framework java not detected (found: [])
**Metrics:**
- files: 4
- frameworks: []
- overall_parse_rate: 1.0
- symbols: 15

## PASS B/rust_app (0.0s)
**Warnings:**
- Framework rust not detected (found: [])
**Metrics:**
- files: 1
- frameworks: []
- overall_parse_rate: 1.0
- symbols: 4

## PASS B/vue_app (0.0s)
**Metrics:**
- files: 2
- frameworks: ['vue']
- parsed_files: 1
