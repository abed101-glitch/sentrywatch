# Deploying the live demo

The whole product is one FastAPI service that also serves the four pages. There is
no separate front end to host and no database server — SQLite lives in the
container's own disk.

## What is committed and why

| File | Size | Why |
|---|---|---|
| `data/creditcard_sample.csv` | 13 MB | The full dataset is 144 MB, over GitHub's 100 MB limit. This is a stratified sample: **all 492 real frauds** plus 25,000 real normal rows. Nothing is generated. |
| `data/model.joblib` | 1.7 MB | The trained Isolation Forest. The server can't retrain on boot, so the artefact ships. |

`data/creditcard.csv` (the full file) stays gitignored. If it is present locally,
`replay.py` prefers it; on the server it falls back to the sample automatically.

**`scikit-learn` is pinned to 1.9.0** in `requirements.txt` because that is the
version that trained `model.joblib`. A different minor version will not unpickle it.

## Deploy on Render

1. Push to GitHub (see below).
2. Go to **render.com** → New → **Blueprint**, and point it at the repo.
   `render.yaml` supplies the build command, start command and environment.
3. First build takes about 5 minutes — it installs scikit-learn and pandas.
4. You get a URL like `https://sentrywatch.onrender.com`.

To deploy without the blueprint, create a Web Service by hand:

- Build command: `pip install -r requirements.txt`
- Start command: `cd src && uvicorn scoring_service:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

### Free tier: read this before demoing

The free plan **sleeps after 15 minutes of inactivity** and takes roughly 50
seconds to wake. Open the URL two or three minutes before you present so it is
warm. Do not click it for the first time in front of the room.

SQLite is on ephemeral disk, so `events.db` and `baselines.db` reset on every
restart. For a demo that's an advantage — every run starts clean.

## Driving the demo without n8n

n8n is not hosted. The deployed service generates its own traffic instead:

| Route | Does |
|---|---|
| `POST /feed/start?interval=1` | replays real transactions through the full scoring path, one per second |
| `POST /feed/stop` | stops it |
| `GET /feed/status` | is it running |

The dashboard has a **Start live feed** button wired to these, so the hosted demo
runs from the browser with nothing installed. The n8n workflow is still the Class 9
deliverable and is shown from the laptop.

## Pages

| Path | |
|---|---|
| `/` | landing |
| `/setup` | onboarding — creates a real account namespace |
| `/checkout` | merchant checkout, scores inline |
| `/dashboard` | live recall and precision against real fraud labels |
| `/health` | status and the active escalation policy |

## Pushing to GitHub

```bash
cd ~/Downloads/CSE299_Project
git init                      # skip if already a repo
git add -A
git commit -m "Real-time fraud detection pipeline — CSE 299"
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git branch -M main
git push -u origin main
```

If the remote already exists, replace `git remote add` with:

```bash
git remote set-url origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
```

**Before pushing, confirm no secrets are going up:**

```bash
git status --short | grep -E "\.env$" && echo "STOP — .env is staged" || echo "clean"
```

`.env` is gitignored. `.env.example` shows the shape without the values.
