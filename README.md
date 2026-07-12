# TrainMe

TrainMe is a simple Python website for training help with three tracks:

- Athlete
- Active
- Getting started

Each track has the subcategories strength, mixed, and cardio. Visitors can use the site without an account, but AI help and Strava-based insights are locked behind an account.

## Run locally

```powershell
python app/main.py
```

Open `http://127.0.0.1:8000`.

## Deploy so the site stays online

TrainMe needs a web service because it has accounts, SQLite data, and Strava OAuth. A normal static website host is not enough.

One simple option is Render:

1. Push this repository to GitHub.
2. Create an account at `https://render.com`.
3. In Render, create a new Blueprint or Web Service from the GitHub repository.
4. If you use the included `render.yaml`, Render will use:
   - `python app/main.py` as the start command
   - `HOST=0.0.0.0`
   - a persistent disk at `/var/data`
   - `TRAINME_DB_PATH=/var/data/trainme.db`
5. Add these environment variables in Render:
   - `STRAVA_CLIENT_ID`
   - `STRAVA_CLIENT_SECRET`
   - `STRAVA_REDIRECT_URI`
6. Set `STRAVA_REDIRECT_URI` to your deployed callback URL, for example:

```text
https://your-trainme-site.onrender.com/strava/callback
```

After deployment, the site stays online from Render's server even when your computer is turned off.

## Strava connection

Regular users only need to click `Connect Strava`, log in to Strava, and approve TrainMe. They should not enter API keys or a username.

As the TrainMe owner, you need to add the Strava API keys once on the server:

Create a Strava app at `https://www.strava.com/settings/api` and set the callback domain to `127.0.0.1` for local development.

Set these environment variables before starting the server locally:

```powershell
$env:STRAVA_CLIENT_ID="your_client_id"
$env:STRAVA_CLIENT_SECRET="your_client_secret"
$env:STRAVA_REDIRECT_URI="http://127.0.0.1:8000/strava/callback"
python app/main.py
```

TrainMe does not fetch Strava data by username. The user must approve the connection through Strava OAuth before the AI bot can use training data.
