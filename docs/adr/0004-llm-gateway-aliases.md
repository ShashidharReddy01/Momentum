# ADR-0004: OpenAI-compatible LLM gateway with model aliases
- **Status:** Accepted · **Date:** 2026-09-23
## Context
The office provides LiteLLM (OpenAI-compatible) in front of AWS Bedrock Claude models and Cohere Embed v3. Local dev may use a different LiteLLM or none.
## Decision
All AI calls go through `momentum.ai.llm` using the OpenAI Python SDK with a configurable `base_url`. Code references only aliases (`fast`, `default`, `smart`, `embed`). Structured output via tool calling. Mock and record modes for tests. A `llm-check` command verifies gateway capabilities.
## Consequences
Provider-agnostic; environment moves are config changes. Some provider-specific features (e.g., prompt caching controls) may be unavailable through the proxy. Acceptable.

## Amendment (2026-09-26, S3.1.1)
The product owner's own setup is **Portkey** (OpenAI-compatible, key in an `x-portkey-api-key` header, models addressed as `@<provider-config>/<bedrock-model-id>`), not LiteLLM. The decision stands unchanged: any OpenAI-compatible gateway works. Two settings make the difference config-only: `MOMENTUM_LLM_API_KEY_HEADER` (which header carries the key) and `MOMENTUM_LLM_EXTRA_HEADERS` (non-secret routing headers). Retries are owned by `ai/llm.py` (the SDK's own retries are off) so 429 `Retry-After`, backoff and `llm_calls` logging behave the same on every gateway. Note: OpenAI SDK 3.x brings its own HTTP stack (`httpx2`) as a transitive dependency; tests inject an `httpx2.MockTransport` into it to exercise the real SDK path offline.
