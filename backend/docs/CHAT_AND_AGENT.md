# Streaming chat and agent workspace

## What was added
| Area | Files |
|---|---|
| Streaming chat API (SSE), private threads | `app/routers/chat.py`, `app/services/chat_engine.py`, `app/services/llm.py`, `app/services/sse.py` |
| Agent plan -> approve -> execute, run history, report | `app/routers/agent_runs.py`, `app/ai/agent/runner.py` |
| New tables (`chat_conversations`, `chat_messages`, `agent_runs`) | `app/models.py`, `alembic/versions/20261022_chat_agent.py` |
| Startup embedding warm-up | `app/main.py`, `app/services/embeddings.py` |
| Tests, benchmark | `tests/test_chat_agent.py`, `scripts/bench_chat.py` |

Nothing existing was removed. `/assistant/ask`, `/agent/run` and `/assistant/answer` still work exactly as before.

## Chat: `POST /chat/stream`
Messages are routed first: **smalltalk** ("hi", thanks) is answered directly; **general** questions go straight to the language model (no knowledge-base match needed; without a model the reply says so); **carebridge** questions use live records, role-scoped facts (verification, donations, needs that have waited) and approved knowledge. `regenerate: true` answers the last question again. `GET /chat/conversations?q=` searches titles and message text (own conversations only).
Body `{"message": "...", "conversation_id": null | 12}`. The response is `text/event-stream`:

| event | data | meaning |
|---|---|---|
| `conversation` | `conversation_id, request_id, title` | first byte, sent before any retrieval |
| `status` | `stage, label` | real progress: understanding, searching, writing |
| `sources` | `knowledge, live, records, confidence, notice` | the evidence, sent before the answer text |
| `token` | `t` | answer text as it is produced |
| `done` | `message_id, mode, model, validation, follow_ups, timings` | final metadata, including `first_token_ms` and `total_ms` |
| `error` | `message, code` | `busy`, `not_found`, `server` ... |

Answer `mode` always says where the text came from: `llm_grounded` (model wrote it from the supplied evidence), `live_analysis` (calculated from database records), `retrieval_only` (quoted knowledge-base passages), `low_confidence`, `no_sources`, `llm_partial`, `interrupted`.
**Real token streaming happens only when a language model is configured** (see `.env.example`: `LLM_API_KEY`, or `LLM_BASE_URL` for Ollama). Without one, the retrieval / live-analysis answer is sent in small chunks and labelled as such. The first status event still arrives immediately.

Safeguards: threads are visible only to their owner (other users get 404); one in-flight message per conversation; 30 messages per user per minute; the model prompt is capped (6 recent messages, 9,000 characters of evidence); model timeout 30 s with one attempt and an immediate fall-back to retrieval; numbers in a model answer that appear in none of the supplied evidence are listed in `validation.ungrounded_numbers` and shown to the user (streamed text cannot be recalled, so this is a visible warning, not a silent edit); an interrupted answer is stored with a clear marker.

## Agent: plan, approve, execute
1. `POST /agent/runs {"goal"}` plans only. Status `awaiting_approval`. No tool runs.
2. `POST /agent/runs/{id}/approve {"create_proposals": false}` (owner only, once) streams `run`, `step_start`, `step_done`, `answer`, `done`.
3. `POST /agent/runs/{id}/reject` discards the plan. `GET /agent/runs`, `GET /agent/runs/{id}`, `GET /agent/runs/{id}/report` (Markdown).

Every step is re-validated against the tool registry and typed inputs at execution time; admin-only tools are refused for other roles; proposal-creating tools only create review-queue proposals, and only when an administrator ticks the box; read-only tools get one retry; a 90 s budget bounds the run; the final text is built only from tool outputs and every number is checked against them. Plan, approval, completion and proposals are written to the audit trail.
The agent uses the 12 existing tools. No new tools (volunteer matching, notification drafting, delivery follow-ups) were added.

## Operational notes
* The in-flight and rate-limit guards and the "running" run marker live in process memory: correct for one Uvicorn worker. Use a shared store (Redis) before running several workers.
* Put `proxy_buffering off` on any reverse proxy in front of `/api` (the supplied `nginx.conf` already does).
* `python scripts/bench_chat.py --email ... --password ...` prints p50/p95 for the old and new endpoints on your machine.

## Language model administration
`GET /admin/llm/status` (key masked, usage, limits) and `POST /admin/llm/test` (one real tiny request). Credentials live only in the server environment. Provider failures are retried with backoff before any text is produced; the usage table stores no prompt or answer text.
