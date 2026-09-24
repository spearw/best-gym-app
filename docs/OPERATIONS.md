# Operations

Running the site on Render: the services, the settings to set by hand, form-video storage
on Cloudflare R2, the hourly cron job, backups, and the rate limits. The build plan
(`docs/BUILD_PLAN.md`, "Render deployment") explains why it's set up this way; this file
is the checklist.

## Free-tier trial (now)

While the client tries the UI, `render.yaml` runs everything on Render's free plans. The
full setup below (paid plans, the cron job, email, form videos) is kept in
`deploy/render.paid.yaml`, ready for real use.

What's different on the free trial:

| | Free trial | Real use (paid) |
| --- | --- | --- |
| Web service | `free`: sleeps after 15 idle minutes, about a minute to wake | `starter`, always on |
| Database | `free`: 1 GB, **deleted 30 days after it's created**, no backups | paid plan with daily backups |
| Migrations | at start-up (free has no pre-deploy step) | pre-deploy step |
| Cron job | none: no morning digest, no video clean-up; the dashboard still updates alerts when opened | hourly `manage.py cron` |
| Email | off: invites are shared with "Copy link"; password resets can't be sent | Resend or Postmark |
| Form videos | off: no "Add a form video" button | Cloudflare R2 |
| Demo data | loaded once at first start (`seed_demo --if-empty`) | not loaded |

Setting it up:

1. Render dashboard → **New → Blueprint** → pick the GitHub repo. It creates the
   `gymtrainer` web service and the `gymtrainer-db` database, both free.
2. When it asks for `DEMO_PASSWORD`, choose a password for the demo accounts (not the
   published local one; the site refuses to seed without it). Give it to the client.
3. The first start migrates and loads the demo gym: coach `dana@ironridge.example` and
   athletes such as `riley@ironridge.example`, all with that password. The client can
   also sign up as a coach of their own gym and invite athletes with "Copy link".
4. Note the database's creation date: Render deletes a free database after 30 days
   (with a 14-day grace period). Move to paid before then if the trial data matters.

The demo's dates are relative to the day it was seeded, so the demo week drifts into the
past as the trial goes on.

## Moving to paid

1. Copy `deploy/render.paid.yaml` over `render.yaml`, commit and push; sync the Blueprint
   in the Render dashboard. It moves the web service to `starter`, adds the hourly
   `gymtrainer-cron` job and the email and storage settings.
2. Upgrade the existing database to a paid plan in the dashboard, rather than creating a
   new one (a new database would start empty).
3. Set the settings in "Settings to set in the Render dashboard" below, and set up R2
   ("Form videos on Cloudflare R2").
4. Remove `DEMO_PASSWORD`, and delete the demo gym's coach and athletes if the client's
   real gym is going in alongside it.

## Services (`deploy/render.paid.yaml`)

| Service | What it runs |
| --- | --- |
| `gymtrainer` (web) | gunicorn, 3 workers; migrations run in the pre-deploy step |
| `gymtrainer-cron` (cron, hourly) | `manage.py cron`: attention alerts, form-video clean-up, each gym's 7am digest |
| `gymtrainer-db` (Postgres 16) | the database; see "Backups" for the plan it needs |

**After syncing the blueprint that introduced `gymtrainer-cron`**, delete the old
`gymtrainer-nightly` cron service in the Render dashboard. Render doesn't remove services
a blueprint no longer lists.

## Settings to set in the Render dashboard

Set these on **both** the web service and the cron job, unless marked otherwise.

| Variable | Example | Notes |
| --- | --- | --- |
| `EMAIL_PROVIDER` | `resend` | or `postmark`; without it email goes to the log |
| `EMAIL_API_KEY` | | from the provider |
| `DEFAULT_FROM_EMAIL` | `Platform <coach@yourdomain>` | a sender the provider has verified |
| `SITE_URL` | `https://gymtrainer.onrender.com` | cron job only: the digest's links |
| `STORAGE_ENDPOINT` | `https://<account id>.r2.cloudflarestorage.com` | form videos |
| `STORAGE_BUCKET` | `gymtrainer-videos` | |
| `STORAGE_ACCESS_KEY` | | R2 API token's access key id |
| `STORAGE_SECRET` | | R2 API token's secret |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | `app.yourdomain.com`, `https://app.yourdomain.com` | web only, once a custom domain is added |

Without the four `STORAGE_*` settings the site works and the athlete app simply has no
"Add a form video" button.

## Form videos on Cloudflare R2

Athletes' form videos go straight from their phone to the bucket (a signed upload URL,
15 minutes, exactly the file's size, at most 200 MB); Django never handles the bytes.
Coaches watch them from a signed link that lasts an hour. Files are deleted 90 days after
upload; the session keeps a note that there was one and the coach's feedback.
Exercise demo videos are unaffected: they stay YouTube links.

1. In Cloudflare: **R2 → Create bucket**, e.g. `gymtrainer-videos`, location automatic.
   Leave public access **off**.
2. **R2 → Manage API tokens → Create API token**: permission *Object Read & Write*,
   limited to that bucket. Copy the access key id, the secret and the S3 endpoint
   (`https://<account id>.r2.cloudflarestorage.com`).
3. Set the four `STORAGE_*` variables on the web service and the cron job.
4. Allow uploads from the site (CORS). Either run, from the web service's Render shell:

       python manage.py storage_setup --origin https://gymtrainer.onrender.com

   (add another `--origin` for a custom domain), or in Cloudflare: **bucket → Settings →
   CORS policy**:

   ```json
   [{"AllowedOrigins": ["https://gymtrainer.onrender.com"],
     "AllowedMethods": ["PUT", "GET", "HEAD"],
     "AllowedHeaders": ["*"],
     "MaxAgeSeconds": 3600}]
   ```
5. Check: as an athlete, add a video in the session player; it should upload with a
   progress bar and appear in the coach's feed.

Locally and in CI a MinIO container stands in for R2 (`make db` starts it and creates the
bucket).

## The cron job

`manage.py cron` runs at minute 0 of every hour:

- brings every coach's "Needs your attention" feed up to date (the same checks the
  dashboard runs when it's opened);
- deletes form videos older than 90 days, and uploads that were started a day ago but
  never finished;
- sends the morning digest to coaches whose gym has just reached 7am, if something new
  needs their attention (coaches can turn it off in Settings).

Its log line reads `cron: N video(s) expired, N unfinished upload(s) removed, N digest(s) sent`.

## Backups

Render's **free** Postgres has no backups and expires; the build plan calls for the
smallest paid instance, which has daily backups. `render.yaml` doesn't set a plan yet:
choose one in the dashboard (or add `plan:` to the database in `render.yaml`) before real
athletes' data goes in.

**Restore drill** (do it once before launch, then every few months):

1. Render dashboard → the database → **Recovery / Backups** → restore the latest backup
   to a **new** database (never over the live one).
2. Open a shell on the web service with the new database's internal URL:

       DATABASE_URL=<restored database URL> python manage.py backup_check

   and compare with `python manage.py backup_check` against the live database. The
   counts should match up to the backup's time, and "newest finished session" should be
   from shortly before it.
3. Delete the restored database afterwards (it costs money while it exists).

## Rate limits

Counts live in the database cache (table `cache`, created by a migration), shared by all
workers. Over a limit a request gets "Slow down" (429).

| What | Limit |
| --- | --- |
| Sign-in | 10 tries per 15 minutes per address and email |
| Password reset | 5 per hour per address |
| Coach sign-up, joining by invite | 10 per hour per address |
| Invites | 30 per hour per coach |
| Messages | 30 per minute per person |
| Form-video uploads | 20 per hour per athlete |

## Installing the athlete app

The athlete app is installable (a PWA): `/manifest.webmanifest`, a service worker at
`/sw.js` that caches the CSS/JS and shows an offline page when there's no signal, and an
"Install the app" card on the athlete's Home (a button on Android/Chrome; the Share → Add
to Home Screen steps on iPhone). Sets are not queued offline yet (build plan, "Still open").
