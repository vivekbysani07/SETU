# Setu — full-stack app (frontend + backend + database, connected)

This is one runnable app now, not separate pieces. Run one command, open one
URL, and you get the frontend, backed by a real API, backed by a real
database.

**Presenting to judges?** See **[`JUDGES.md`](./JUDGES.md)** instead — this file is the
technical/developer reference; that one is the pitch: problem, solution, architecture
diagrams, and a point-by-point map from the hackathon brief to what's actually built.

```
setu-backend/
├── main.py          FastAPI app — serves the frontend AND the API
├── static/
│   └── index.html   the frontend (served automatically at "/")
├── models.py         database tables: Region, CitizenRequest
├── database.py       DB connection (SQLite by default, Postgres/Cloud SQL via env var)
├── seed_data.py       demographic/infra/investment data for 5 BRICS countries
├── ai_client.py        Gemini classification + brief generation (+ offline mock fallback)
├── requirements.txt
├── Dockerfile
├── .env.example
├── JUDGES.md                  the presentation-style README — start here for a demo/pitch
├── CLOUD_DATABASE_SETUP.txt   step-by-step Google Cloud SQL guide (needs a card on file)
└── FREE_HOSTING_SETUP.txt     no-card-anywhere guide: Aiven free Postgres + Render free hosting
```

## 1. Run it — one command

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then add your GEMINI_API_KEY (see step 2)
python main.py
```

Open **http://127.0.0.1:8000** — that's the frontend, served directly by the backend, same
origin, nothing to configure. You'll land on a page that asks you to pick a language, then
whether you're a Citizen or a Policymaker (admin login).

Interactive API docs: **http://127.0.0.1:8000/docs**

The first run creates `setu.db` (SQLite) and seeds it with region data automatically —
you'll see it appear in the folder.

<details>
<summary><b>What was fixed in this pass</b> (click to expand)</summary>

- **`.env` was silently ignored.** `python-dotenv` was listed as a dependency but
  `load_dotenv()` was never actually called, so `GEMINI_API_KEY` in `.env` never reached
  `os.getenv()` — everything ran in offline-mock mode no matter what you put in the file.
  Fixed: `main.py` now calls `load_dotenv()` first, before any module reads an environment
  variable. Confirm it worked via `GET /api/health` → `"ai_mode": "live (Gemini)"`.
- **`.env.example` didn't actually exist.** The README told you to copy a file that wasn't
  in the project. It's here now, with the exact variable names the code reads (`ADMIN_ID`,
  not `ADMIN_USERNAME` — a naming drift from an earlier draft).
- **Gemini calls could take the whole request down.** A rate limit, a safety block, or a
  slightly malformed response would raise an exception and 502 the citizen's submission.
  `ai_client.py` now forces JSON output (`response_mime_type`) and falls back to the offline
  classifier for that one message if the live call fails, instead of failing the request.
- **Cloud database connections could go stale.** Free-tier Postgres (Aiven, Cloud SQL) can
  drop idle connections; the next request to grab one would 500. `database.py` now sets
  `pool_pre_ping=True`, so a dead connection is caught and replaced automatically.
- **The mic button lied about voice support.** On a browser without the Speech API, the
  button still said "🎤 Speak" until you clicked it once and got silently disabled — and a
  language change afterward would reset the label back, hiding the fact it didn't work. It's
  now disabled correctly from page load, in every language.
- **No visible proof the AI/database are real.** Added a one-line status badge under the
  Policymaker dashboard heading (`AI: live (Gemini) · DB: postgres / cloud sql`), pulled live
  from `/api/health`, so this is visible without opening dev tools — worth pointing out
  during a demo.

</details>

## 2. Get a real Gemini API key (so the AI classification is live, not mocked)

1. Go to **https://aistudio.google.com/app/apikey**
2. Sign in with your Google account and click **Create API key**
3. Copy the key into your `.env` file: `GEMINI_API_KEY=your_key_here`
4. Restart `python main.py`

Without a key, the app still runs completely — it just falls back to a simple offline
keyword-based classifier so you can test everything else. Check which mode you're in
anytime via the status line under the Policymaker dashboard heading once logged in, or
directly at `GET /api/health`:
`{"ai_mode": "live (Gemini)" | "offline mock — set GEMINI_API_KEY", ...}`

## 3. Create a cloud database (Cloud SQL for PostgreSQL)

SQLite is fine for local testing, but it's a single file — not something you'd point a
real national platform at. **Full step-by-step walkthrough: see `CLOUD_DATABASE_SETUP.txt`**
in this same folder — it covers creating the instance, connecting from your laptop for
testing, and connecting from Cloud Run for the real deployment, in more detail than the
summary below.

**Don't want to enter a card anywhere?** Google Cloud SQL's free tier still requires one on
file even though it doesn't charge you. `FREE_HOSTING_SETUP.txt` in this same folder covers
a no-card-anywhere alternative instead: Aiven's free PostgreSQL (permanent, no card) paired
with Render's free Web Service (also no card) for the backend itself. Same DATABASE_URL
mechanism either way — nothing in the code changes.

**a. Enable the API and create the instance** (replace `setu-db` / region / password as you like):

```bash
gcloud services enable sqladmin.googleapis.com

gcloud sql instances create setu-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --root-password=CHOOSE_A_STRONG_PASSWORD
```

This takes a few minutes to provision.

**b. Create the database and a user inside it:**

```bash
gcloud sql databases create setu --instance=setu-db

gcloud sql users create setu-user \
  --instance=setu-db \
  --password=CHOOSE_A_STRONG_PASSWORD
```

**c. Get the instance's connection name** — you'll need this string in two places below:

```bash
gcloud sql instances describe setu-db --format='value(connectionName)'
# prints something like: your-project:us-central1:setu-db
```

**d. Connect to it from your laptop (for local testing)** using the Cloud SQL Auth Proxy —
this is the officially recommended way to reach Cloud SQL securely without opening it to
the public internet:

```bash
# download the proxy once: https://cloud.google.com/sql/docs/postgres/sql-proxy#install
./cloud-sql-proxy your-project:us-central1:setu-db --port 5432
```

Leave that running in its own terminal, then in your `.env`:

```
DATABASE_URL=postgresql+psycopg2://setu-user:CHOOSE_A_STRONG_PASSWORD@127.0.0.1:5432/setu
```

Restart `python main.py` — it will now create its tables in Cloud SQL instead of the local
SQLite file. `GET /api/health` should report `"database": "postgres / cloud sql"`.

**e. Connect to it from Cloud Run (for a real deployment)** — no proxy needed here, Cloud Run
talks to Cloud SQL over a private Unix socket automatically when you attach the instance:

```
DATABASE_URL=postgresql+psycopg2://setu-user:CHOOSE_A_STRONG_PASSWORD@/setu?host=/cloudsql/your-project:us-central1:setu-db
```

(See the full `gcloud run deploy` command in step 4 — this is exactly the `--set-env-vars`
value it uses, and `--add-cloudsql-instances` is what makes that socket path exist.)

## 4. Deploy to Cloud Run

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/setu-app

gcloud run deploy setu-app \
  --image gcr.io/YOUR_PROJECT/setu-app \
  --add-cloudsql-instances your-project:us-central1:setu-db \
  --set-env-vars GEMINI_API_KEY=your_key,DATABASE_URL="postgresql+psycopg2://setu-user:CHOOSE_A_STRONG_PASSWORD@/setu?host=/cloudsql/your-project:us-central1:setu-db" \
  --allow-unauthenticated \
  --region us-central1
```

The command prints a public `https://setu-app-xxxx-uc.a.run.app` URL — open it, and you get
the same frontend, now backed by Cloud SQL and a real Gemini key, reachable from anywhere.

## API endpoints (all used by the frontend)

Public — no login needed (the citizen side):
- `GET  /` — the frontend itself
- `GET  /api/health` — AI mode + database type, for diagnostics
- `GET  /api/countries` / `GET /api/regions?country_code=IN`
- `POST /api/requests` — submit + classify a citizen request
- `GET  /api/my-requests?country_code=IN&citizen_id=...` — one citizen's requests + status
- `POST /api/admin/login` — `{user_id, password}` → `{token}` on a correct match, 401 otherwise

Admin-only — require an `Authorization: Bearer <token>` header, from `/api/admin/login`:
- `GET  /api/requests?country_code=IN` — all requests for a country
- `GET  /api/dashboard?country_code=IN` — stats, hotspots, ranked priority projects
- `POST /api/brief` — AI-generated project title + policy brief
- `DELETE /api/requests?country_code=IN` — clear demo data

Tokens live in server memory (`_admin_tokens` in `main.py`) — a restart logs everyone out,
and multiple Cloud Run instances won't share sessions. Fine for a demo; a real deployment
needs a proper session store and per-user accounts instead of one shared login.

## Severity rubric and priority formula

Both live in `ai_client.py` (`SEVERITY_RUBRIC`) and `main.py` (`compute_groups`,
`compute_hotspots`) respectively — see the code comments there for the exact 1–5 rubric
text and the `count × severity × poverty × infra-gap × investment-gap` scoring formula.

## Honest notes

- **Real**: the FastAPI service, the database (SQLite locally, Postgres in the cloud), every
  endpoint, the scoring formula, and — once `GEMINI_API_KEY` is set — the AI classification
  and brief generation, with a graceful per-message fallback if a single Gemini call fails
  rather than a hard error for the whole request.
- **Mocked for the demo**: the region data in `seed_data.py` stands in for real census /
  infrastructure-ministry / public-investment-plan datasets. The WhatsApp channel toggle is
  simulated — a real build points a WhatsApp Business API webhook at `POST /api/requests`.
  The admin login is one shared demo account, not real per-user accounts.
- **Scope right now**: country is fixed to India, with Andhra Pradesh given extra region
  coverage (Visakhapatnam, Vijayawada, Guntur, Tirupati, Rajahmundry, Nellore, Kurnool,
  Kadapa, Anantapur, Srikakulam) alongside Assam, Odisha, Maharashtra, Gujarat and Uttar
  Pradesh. Brazil/Russia/China/South Africa data and the `country_code` parameter are still
  in `seed_data.py` and the API, just unused for now — reintroducing a country switcher later
  is a frontend change, not a backend one.
- **Translation quality**: the Hindi/Telugu/Kannada/Tamil/Malayalam interface text was
  machine-translated by the AI that built this, not reviewed by a native speaker of each
  language — worth a proofread before a real public launch, solid enough for a demo as is.
- **Sandbox note**: this pass was a careful code review, not a live test run — I fixed
  everything I could find by reading the code (syntax-checked, cross-referenced every ID and
  env var name against where it's actually used) in a sandbox with no internet access, so I
  still couldn't click through the running app myself. Do one real run-through before
  presenting.

## Portals, login, languages, theme

- The landing page lets people pick **User portal** (citizen portal + my requests) or **Admin portal** (policymaker view).
- Admin login is checked by the backend. Set `ADMIN_ID` and `ADMIN_PASSWORD` in `.env` / the environment
  (defaults: `admin` / `setu@123` — change them before deploying). The dashboard, all-requests, brief and
  clear-data endpoints return 401 without a valid admin login.
- Admin sessions are kept in server memory, so a restart logs admins out (and multiple Cloud Run instances need
  a shared session store).
- Languages: English, Hindi, Telugu, Kannada, Tamil, Malayalam — chosen on the landing page, changeable in Settings.
- Light/dark theme toggle is in the top bar. India only; Andhra Pradesh areas are in `seed_data.py`.
- An **About** tab (also reachable from the landing page before picking a role) explains what
  Setu does in plain language, translated into all six interface languages — the content
  lives in the `T` object in `static/index.html` under the `tAbout` / `about*` keys.
- The Policymaker dashboard shows a live status line (`AI: ... · DB: ...`) pulled from
  `GET /api/health` — visible proof the classification and database are real, without
  needing to open dev tools.
- All configuration is in `.env.example` — copy it to `.env` and fill in what you have.
  Every value has a safe default, so the app runs with nothing configured at all.
