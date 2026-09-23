# ADR-0004: OpenAI-compatible LLM gateway with model aliases
- **Status:** Accepted · **Date:** 2026-09-23
## Context
The office provides LiteLLM (OpenAI-compatible) in front of AWS Bedrock Claude models and Cohere Embed v3. Local dev may use a different LiteLLM or none.
## Decision
All AI calls go through `momentum.ai.llm` using the OpenAI Python SDK with a configurable `base_url`. Code references only aliases (`fast`, `default`, `smart`, `embed`). Structured output via tool calling. Mock and record modes for tests. A `llm-check` command verifies gateway capabilities.
## Consequences
Provider-agnostic; environment moves are config changes. Some provider-specific features (e.g., prompt caching controls) may be unavailable through the proxy. Acceptable.
