# CareBridge backend: what was fixed, and how to run and check it

## 1. Why login / reading data failed (and what changed)

You reported: *register writes rows into `users` and `organizations`, but login returns 500, and
screens never show data from the tables.* The code now handles every cause I could find. Run
`python scripts/check_schema.py` (or open `http://127.0.0.1:8000/health/db`) to see which of these
applied to **your** database in a few seconds.

| # | Problem | Fix |
|---|---------|-----|
| 1 | Password check used `passlib`, which is unmaintained and breaks with newer `bcrypt` / Python releases. A malformed hash raised an exception = **500 on login**. | `app/auth.py` now uses `bcrypt` directly. Hashes made by the old code still verify (tested). A bad hash is a 401, never a 500. |
| 2 | `/needs/alerts` crashed with a `NameError` (`Need` was never imported) = 500 for every organization account. | Import fixed; endpoint now returns the need name, urgency and quantity. |
| 3 | Output models required non-NULL values (`NeedOut`, `OrganizationOut`, `DonorOut`, ...). One row inserted by hand in pgAdmin with an empty column made the **whole list return 500**, so screens looked empty. | Output models accept NULLs. Regression test inserts a row full of NULLs. |
| 4 | `token_version` NULL in the database (older rows) made the token check fail, so every request after login was 401 and the UI bounced back to the login page. | `dependencies.py` treats NULL as 0. |
| 5 | Login was case-sensitive on the e-mail and returned only `{id,email,role}`. | Case-insensitive lookup; login/register/`/auth/me` now include `display_name` (organization / donor / volunteer name). |
| 6 | If the database schema is behind the models (a migration was not applied) every query on `users` fails with 500. | `/health/db` and `scripts/check_schema.py` compare the live tables and columns with the models and print the fix (`alembic upgrade head`). |
| 7 | An unexpected error returned a bare "Internal Server Error". | Errors are logged with a traceback and returned as JSON with a hint, so the UI shows a useful message. |

## 2. New / improved endpoints used by the new frontend

* `GET /dashboard/summary` role-scoped counts, monthly donations, needs by urgency/category (all read live from the tables)
* `GET /health/db` connection, schema drift, row counts, RAG index status
* `GET /fraud/flags`, `POST /fraud/scan` list flags with the donation details, and screen every unflagged donation
* `GET /matching/`, `GET /needs/alerts` return need category, donor/volunteer names
* `GET /children/{id}`; organizations no longer need to send `org_id` when creating children/needs
* `POST /auth/users/{id}/reset-code` admin-issued one-time password reset code (for servers without e-mail)
* `GET /assistant/status`, `POST /assistant/reindex` RAG index status and re-embedding of rows added by SQL

## 3. Run it

```bash
cd backend
python -m venv venv && venv\Scripts\activate        # Windows (use the SAME terminal for every command below)
pip install -r requirements.txt
```
If `uvicorn` says *"not recognized"*, the virtual environment is not active in that terminal. Run
`venv\Scripts\activate` first, or use `python -m uvicorn app.main:app --reload`.

**Existing database (yours):**
```bash
alembic upgrade head            # brings the schema to the latest revision (20261010_frames)
python scripts/check_schema.py  # must print "OK Database reachable and schema matches the code"
python -m uvicorn app.main:app --reload
```
**Brand-new empty database:**
```bash
python scripts/init_db.py        # creates all 16 tables and stamps Alembic
python scripts/create_admin.py   # first administrator
```
`.env` needs `DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/carebridge` and a long random `SECRET_KEY`.

## 4. Demo data for a good demonstration

1. Register an **organization** account in the website (e.g. `hope@demo.org`).
2. `python scripts/seed_demo.py --org-email hope@demo.org` adds children, needs, donors, volunteers, donations
   and 12 knowledge-base entries, and marks the organization verified.
3. `python scripts/embed_knowledge_base.py` embeds the knowledge base for the RAG assistant (first run downloads the
   `all-MiniLM-L6-v2` model, about 90 MB, so it needs internet once).

## 5. RAG assistant: how it talks to the database

`POST /assistant/ask` embeds the question, reads `knowledge_base` rows (global rows + the caller's own
organization rows), ranks them by cosine similarity, returns the top 3 with their source, and writes the
question/answer/sources to `assistant_messages`. Without `OPENAI_API_KEY` it is retrieval-only (the UI says so);
with a key it asks the model to answer only from those passages. `GET /health/db` shows `embedded_entries`;
if rows were added by SQL, run `python scripts/embed_knowledge_base.py` or press **Index new** in the UI.

## 6. Tests

```bash
python -m pytest -q          # 38 tests, no external services needed (SQLite in memory, fake embedder)
```
Includes: register -> login -> read per role, wrong password = 401, corrupt hash = 401, old passlib hashes still work,
NULL-column rows, cross-organization isolation, fraud/need/matching queues, RAG read+write, reset codes, health check.
