# TrainMe

TrainMe is a simple Python website for training help with three tracks:

- Athlete
- Active
- Getting started

Athlete and Active use strength, mixed, and cardio subcategories. Getting started uses:

- Start training with gym
- Start training without gym
- Lose weight

Visitors can use the site without an account, but AI help, saved training data, calorie history, and Strava-based insights are locked behind an account.

## Run locally

```powershell
python app/main.py
```

Open `http://127.0.0.1:8000`.

## Deploy on Render for free

TrainMe needs a web service because it has accounts, SQLite data, and Strava OAuth. A normal static website host is not enough.

The included `render.yaml` is set up for Render's free web service:

1. Push this repository to GitHub.
2. Create an account at `https://render.com`.
3. In Render, choose **New +** then **Blueprint**.
4. Connect the GitHub repository `fille9904/TrainMe`.
5. Render will read `render.yaml` and create the `trainme` web service with:
   - `plan: free`
   - `python app/main.py` as the start command
   - `HOST=0.0.0.0`
   - `TRAINME_DB_PATH=/tmp/trainme.db`
   - `/` as the health check path
6. Add these environment variables in Render:
   - `STRAVA_CLIENT_ID`
   - `STRAVA_CLIENT_SECRET`
   - `STRAVA_REDIRECT_URI`
   - `OPENAI_API_KEY` if you want AI food-photo calorie estimates
7. Set `STRAVA_REDIRECT_URI` to your deployed callback URL, for example:

```text
https://your-trainme-site.onrender.com/strava/callback
```

8. Click **Apply** or **Deploy**.

After deployment, the site stays online from Render's server even when your computer is turned off.

### Free plan data warning

The free Render setup uses `/tmp/trainme.db`, which is temporary storage. This is fine for testing the site online, but accounts, saved sessions, calories, and Strava connections can disappear after restarts or redeploys.

For real users, switch to one of these later:

- Render persistent disk, which costs a small monthly amount.
- A hosted Postgres database, which is better for a real production app.

### Paid persistent data option

If you later want SQLite data to survive reliably on Render, change `TRAINME_DB_PATH` to `/var/data/trainme.db` and add this disk block back to `render.yaml`:

```yaml
    disk:
      name: trainme-data
      mountPath: /var/data
      sizeGB: 1
```

Then redeploy on a Render plan that supports persistent disks.

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
