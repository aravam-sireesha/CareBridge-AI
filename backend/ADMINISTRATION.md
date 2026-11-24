# CareBridge AI: administration, secure sign-in, workflow, RAG assistant

## 1. Set up (once)
1. `alembic upgrade head` (revisions `20261008_admin`, `20261009_workflow`). Check `http://127.0.0.1:8000/health/db`: `schema.ok` must be `true`.
2. Copy the new settings from `.env.example` into `.env` (all optional; see section 4).
3. Restart the backend (`uvicorn`) and the frontend (`npm run dev`), then hard-refresh the browser.
4. Create the first administrator: set `ADMIN_SETUP_TOKEN` (24+ random characters) in `backend/.env`, restart the backend, open `/admin/setup`, enter the token and the account details, then **delete the token**. Or run `python scripts/create_admin.py` (works only while no administrator exists). Setup closes permanently once an administrator exists.
   Later administrators are added by a signed-in administrator under **Administration > Administrators**.
5. Load the built-in knowledge base: sign in as administrator, open **AI assistant**, press **Load CareBridge guide** (or `python scripts/seed_knowledge.py`).
   If `sentence-transformers` is installed, also run `python scripts/embed_knowledge_base.py` (the loader does this automatically when it can).

## 2. The workflow (matches the five-stage picture)
| Stage | In the app |
|---|---|
| 1 Data input | Children, Organizations, All donors, All volunteers, Resources |
| 2 AI processing | Need alerts, fraud flags, donor / volunteer / resource suggestions, demand forecast, career guidance |
| 3 Decision | AI assistant (RAG) and **Review queue** (administrator approves) |
| 4 Action | Matching, resource allocation (approve, deliver), guidance, coordination |
| 5 Outcomes | Workflow board numbers, organization health, audit trail |

**Administration > Workflow** shows the five stages with live numbers, the pending decisions, predicted demand and recent activity.
**Run all AI scans** runs every analysis in one click. The administrator sees and manages every organization, need, donor, volunteer and resource.
Diagrams for beginners are in `docs/workflow/` and in the app at **How it works** (`/guide`).

## 3. Secure authentication
- **Lockout:** 5 wrong passwords or codes lock the account for 15 minutes. Per-address rate limit on sign-in, sign-up and password reset.
- **Passwords:** at least 12 characters, three kinds of characters, not containing the email name. Changing the password signs out other devices.
- **Two-step verification (administrators):** authenticator app (TOTP, RFC 6238), 8 one-time recovery codes, secret encrypted with a key derived from `SECRET_KEY`, a used code cannot be replayed. A normal sign-in cannot bypass it.
- **Sessions:** "Sign out of all other devices" in Settings > Security.
- **Audit trail:** sign-ins, failures, lockouts, 2FA changes and every administrator decision, append-only (Administration > Audit trail).
- **HTTP headers:** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `no-store` on `/auth` and `/admin`, optional HSTS.
- Not included: per-address limits are in memory (use a proxy or shared store if you run several server processes); the encryption key is derived from `SECRET_KEY`, so changing `SECRET_KEY` makes stored 2FA secrets unreadable (administrators would then re-enrol).

## 4. Settings (all optional, defaults shown in `.env.example`)
`ADMIN_SETUP_TOKEN`, `ADMIN_TOKEN_MINUTES`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES`, `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW`, `TRUST_PROXY`, `FORCE_HTTPS`, `RAG_CONFIDENCE_THRESHOLD`, `OPENAI_API_KEY`.

## 5. AI and ML (what each model really is)
| Part | Method | Learns? |
|---|---|---|
| Donor suggestions | TF-IDF similarity + category match + history + recency + approval rate; then logistic regression | from administrator decisions (after 20) |
| Volunteer suggestions | same idea with skills, availability, history, same organization | yes (after 20) |
| Resource allocation | category relevance, coverage, same organization | rule-based |
| Demand forecast | damped-trend exponential smoothing per category, compared with stock and supply | refits on every call |
| Organization health | transparent 0-100 score with evidence-based tips | rule-based |
| Fraud, need alerts | simple readable rules with scores | rule-based |
| Career guidance | similarity recommender (existing) | feedback stored |

The **AI suggestion hub** (`/admin/recommend`) gives suggestions for any organization, need, donor or volunteer.

## 6. RAG assistant
Hybrid retrieval over the knowledge base: passage chunking, query expansion, BM25 + typo-tolerant character n-grams + dense vectors (when available), reciprocal-rank fusion, reranking, calibrated confidence. Below the threshold it **refuses instead of guessing** and shows the closest passages. Situation questions are answered from the live database (role scoped). Administrators see **questions the assistant could not answer**, the to-do list for new knowledge entries.

### Measured accuracy (retrieval only, keyword + n-gram rankers; dense vectors could not be measured in the build environment)
`python scripts/eval_rag.py [--heldout|--fresh] [--dense]`

| Question set | Questions | Top-1 | Top-3 | Off-topic refused |
|---|---|---|---|---|
| Development (used while tuning) | 99 | 86% | 96% | 15 of 15 |
| Held-out (written before tuning; wording later overlapped the entries' hidden phrasings) | 47 | 87% | 96% | 12 of 12 |
| **Fresh (written after tuning, run once)** | 44 | **43%** | **59%** | 10 of 10 |

Read the fresh row as the realistic one: paraphrases that share few words with an entry are found less often without dense vectors. In that set no answer reached "high" confidence and the "medium" answers were 71% correct, so the assistant mostly says it is unsure rather than guessing. Run `scripts/eval_rag.py --dense --fresh` on your machine (after installing sentence-transformers) to measure the full system, and tune `RAG_CONFIDENCE_THRESHOLD` from that. The question sets are written by the developers; real accuracy needs real user questions, which the "unanswered questions" list collects.

## 7. AI methods, prediction, optimisation and the agent
See `AI_ARCHITECTURE.md` and **Administration > AI Lab**. Regenerate the benchmark report with `python scripts/run_ai_pipeline.py`.

## 8. Tests
`pytest` (backend, 208 tests; run in chunks if your shell has a time limit) and `npm test -- tests/admin-theme.test.jsx tests/workflow-security.test.jsx tests/hub-guide.test.jsx tests/ai-lab.test.jsx` (frontend, 46 tests, no server needed).
`tests/e2e.test.jsx` and `tests/ai-modules.test.jsx` need a running backend and the demo data (`scripts/seed_demo.py`).
