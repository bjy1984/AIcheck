# Performance audit decisions

## Implemented

1. **Model-call ledger lock scope**
   - Confirmed by source inspection: synchronous `flush_state_records()` was executed inside `_MODEL_CALL_LEDGER_LOCK`.
   - Change: attempt number allocation and in-memory insertion remain under the lock; database persistence runs after releasing it.
   - Preserves the existing ledger and avoids introducing a new async event bus.

2. **Redis capacity status keyspace scan**
   - Confirmed by source inspection: readiness used Redis `KEYS` for capacity slot patterns.
   - Slot keys are bounded by configured concurrency, so status now performs fixed-index `EXISTS` checks.

## Measured, not changed in this batch

### API health ledger scan

Synthetic in-process benchmark, five samples per size:

- 1,000 attempts: p50 3.001 ms
- 10,000 attempts: p50 3.488 ms
- 100,000 attempts: p50 10.339 ms

The current scan is linear, but the measured absolute cost did not justify a larger state-summary migration in this batch. The result is retained as a capacity signal. Revisit when real ledger size, probe concurrency, or health p95 materially increases.

### HTTP client pooling

Source inspection confirms per-call client construction in Aliyun OCR, Qwen runtime, and LiteLLM clients. No network benchmark was available without exercising external providers. Pooling is deferred rather than changing connection lifecycle without latency/FD evidence.

### Checkpoint batching and prompt caching

Deferred. Both require production-like storage/provider measurements to avoid reducing crash recovery fidelity or increasing cache-write cost.
