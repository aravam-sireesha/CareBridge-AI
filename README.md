## Full-stack setup

Copy `backend/.env.example` to `backend/.env`, set a random `SECRET_KEY`, and configure `DATABASE_URL`. Keep `.env` private. Apply migrations and start the API from `backend`:

```powershell
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

In a second terminal, start the frontend:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

The Vite development server proxies `/api` requests to `http://127.0.0.1:8000`. Set `VITE_API_URL` in `frontend/.env` only when using a separately hosted API. Open `http://localhost:5173`.

## Accounts and access

Public registration supports organization, donor, and volunteer accounts. Registration creates and links the organization's or supporter’s database record. Public requests cannot grant administrator access. After migrations, provision an administrator interactively from `backend`:

```powershell
python scripts/create_admin.py
```

Organization and supporter data is scoped by account role. AI review decisions and account role management remain administrator-only. Password reset uses a hashed, one-time, 30-minute token. Configure `SMTP_HOST`, `SMTP_FROM`, and the optional `SMTP_*` credentials in `backend/.env`; reset requests otherwise show that mail is unavailable. Responses do not reveal whether an email is registered.

## RAG assistant

The assistant stores each conversation turn and its source matches in the database. Organizations can add approved references in the assistant screen; each entry is embedded on save and scoped to its organization. Seeded entries can be embedded with `python scripts/embed_knowledge_base.py` from `backend`. The first embedding call downloads `all-MiniLM-L6-v2`. Configure `OPENAI_API_KEY` (and optionally `OPENAI_BASE_URL` and `OPENAI_MODEL`) to enable source-grounded natural-language generation. Without an LLM key, the API returns retrieved source excerpts instead of implying a generated answer.

## AI model artifacts

The career artifact is built by running the career notebook through its similarity-recommender cell. It records `career-hybrid-1.1.0` and the scikit-learn version; keep `backend/requirements.txt` aligned with that version. The fraud artifact can be rebuilt with `python -m app.train_fraud_model` from `backend`. It stores the model version, feature list, validation-selected threshold, and holdout precision, recall, and PR-AUC. Request schemas and routes are available at `/docs`.

Career profile JSON uses the exact training feature names. Missing optional values are filled with adapter defaults (`Age=18`, `Gender=Other`, `Field_of_Study=Other`, `Year_of_Study=1`, `University_Location=Region A`, `GPA=0`, boolean indicators `0`, `Employment_Type=None`, and `Entrepreneurial_Aspirations=Low`). Interests must be one of the five training labels; unsupported stored values become `Other` and are ignored by the one-hot encoder. These defaults are approximations, not verified child data.

The career dataset is synthetic. Its interest-to-career crosstab is close to uniform, so the hybrid scores are candidate rankings, not validated predictions. Feedback columns in the supplied CSV are not verified admin decisions. Use prospective records in PostgreSQL for future evaluation. Fraud metrics from `creditcard.csv` are offline dataset baselines, not production performance; report precision, recall, and PR-AUC because fraud is rare.
