# Deploying Church Attendance

This is a practical checklist for putting the app on a real server. Nothing here is needed
for development on your own computer.

## Hosting on Render (API) and Vercel (website)

Sections 1 to 7 below describe one self-managed server. If you use **Render for the backend
and Vercel for the website**, read this section first; it replaces the parts of 1 to 4 that
do not apply.

Two layouts work. **Yours is the first:** the website calls the Render address directly.

```
A (direct)   phone browser -> Vercel (the website only)
             phone browser -> Render (FastAPI, address set in VITE_API_URL) -> PostgreSQL
B (proxy)    phone browser -> Vercel (website + a rewrite of /api/*) -> Render -> PostgreSQL
```

### Vercel (layout A, direct)

- In Vercel, set the environment variable `VITE_API_URL` to your Render address with no slash
  at the end and without `/api`, for example `https://church-attendance-api.onrender.com`, and
  redeploy the website (Vite reads it when it builds).
- On Render, set `CORS_ORIGINS` to include your Vercel address (see the table below).
- `web/vercel.json` only needs the rule that opens the app for every path, so that a
  QR-code link to `/checkin`, a reset link to `/reset-password` or a refresh on `/admin`
  does not show a 404. A file with a single rewrite from `/(.*)` to `/` does this.
- Pictures (profile photos) are loaded from the Render address too; the app adds
  `VITE_API_URL` in front of the picture's path for you.

### Vercel (layout B, proxy; only if you choose it)

Leave `VITE_API_URL` empty and forward `/api` to Render. The order matters, first match wins:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://YOUR-SERVICE.onrender.com/api/:path*" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

Vercel sets the visitor's real address in `x-forwarded-for` on these forwarded requests.

### Render: environment variables

| Variable | Value |
|---|---|
| `DATABASE_URL` | your Postgres address, starting `postgresql+psycopg://` |
| `SECRET_KEY` | a long random string (run `python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
| `ENVIRONMENT` | `production` (the server then refuses a `SECRET_KEY` shorter than 32 characters) |
| `WEB_BASE_URL` | your **production** Vercel address, e.g. `https://church-attendance.vercel.app`, with no slash at the end. Reset links, QR codes and passkeys all depend on it |
| `CORS_ORIGINS` | `["https://church-attendance.vercel.app"]` |
| `FORWARDED_ALLOW_IPS` | `*`. Without it the server sees Render's internal address for everyone, so the signup and password-reset limits would count the whole church as one person |
| `EMAIL_FROM` and `BREVO_API_KEY` (or `RESEND_API_KEY`) | see "Email on Render" below |

Render settings: root directory `backend`; build command `pip install -r requirements.txt`
(this installs the new `cryptography` and `Pillow` packages);
start command:

```
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Putting `alembic upgrade head` in the start command applies any new database change every
time the service starts (it does nothing when the database is already up to date), which
suits the free plan, where there is no separate pre-deploy command.

### Upgrading safely

The database changes in these updates only **add** columns and tables, so the old backend keeps
working while you upgrade. In this order:

1. Update the database: from your computer, in the `backend` folder with the venv active,
   set `DATABASE_URL` to Render's **external** database address and run `alembic upgrade head`.
   (Or skip this step and let the new start command do it on the next deploy.)
2. Deploy the backend to Render and wait for it to be live.
3. Deploy the website to Vercel.

Deploying the new backend code to a database that has not been upgraded makes most pages fail.

### Email on Render

Render's **free plan blocks outgoing email over SMTP** (ports 25, 465 and 587), so password
reset and approval emails would silently never arrive. Use a provider that sends over the
web instead:

- **Brevo** (free tier, can send from one verified address without owning a domain):
  create an account, add and verify a sender address, create an API key, then set
  `BREVO_API_KEY` and `EMAIL_FROM` (the verified address, for example
  `Church Attendance <you@example.org>`) on Render.
- **Resend**: set `RESEND_API_KEY` and `EMAIL_FROM`. To email people other than yourself it
  needs a domain you own and have verified with them.

If a provider refuses an email (for example, the sender is not verified), the reason is
written to the Render logs.

### Free plan: it falls asleep

A free Render service goes to sleep after a period of no traffic, and the first request
afterwards can take up to a minute (it may fail once through Vercel). On a Sunday, that is a
member arriving at the door. Options: upgrade to a paid instance, or point a free uptime
monitor (such as UptimeRobot) at `https://<your-vercel-address>/api/health` every 5 minutes.
The check-in screen asks the server every 10 seconds, so open it 10 minutes before the
service starts to wake the server first.

The free plan also **loses saved files on every restart**. Profile photos are therefore stored in
the database (resized to a small square), not on the disk, so they survive. Photos uploaded
before this change were files on the disk and may already be gone; the app then shows the
member's initials until they upload a new one.

### Fingerprint check-in on Vercel

Passkeys are tied to the exact website address, so `WEB_BASE_URL` must be your production
Vercel address, and everyone must use that address (not a preview link such as
`...-git-branch-...vercel.app`). If you later move to your own domain, every member must set
up their fingerprint check-in again, so decide on the domain before rolling it out.

### Test the hosted site

1. Open your Render address followed by `/api/health` (for example
   `https://church-attendance-api.onrender.com/api/health`): it should answer.
2. Open `https://<your-vercel-address>/checkin` and refresh: it should show the app or the
   sign-in page, not a 404.
3. Forgot password: the email should arrive. If not, read the Render logs.
4. On a phone: Profile > "Set up on this phone", then clock in to a service that requires it.
5. Open the check-in screen on a computer, scan the QR code with a phone, and confirm it
   checks in. Wait a minute and check the code on the screen has changed.
6. In the browser's developer tools (Network tab), an `/api/...` response should show
   `Cache-Control: no-store`.
7. Profile: upload a photo. It should appear straight away and still be there after
   the Render service has restarted or woken from sleep.

## 1. Where to host it

The simplest setup for one church is **one small Linux server (VPS)** that runs everything:
PostgreSQL, the API, and a web server (Caddy) that serves the website and handles HTTPS.
1 vCPU and 1-2 GB of memory is plenty.

- Choose a data centre in **Europe** (Paris, Frankfurt, London). From Cameroon that is
  usually closer, so pages load faster, than the US.
- Alternative: a managed platform (Render, Railway, Fly.io) for the API plus a managed
  PostgreSQL, with the built website on Cloudflare Pages or Netlify. This costs more but
  you do less server work. The settings in section 2 are the same.
- You need a **domain name** (for example `attendance.yourchurch.org`) pointing at the server.

## 2. Settings for production (`backend/.env`)

```
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://appuser:a-strong-password@localhost:5432/church_attendance
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_urlsafe(48))">
CORS_ORIGINS=["https://attendance.yourchurch.org"]
WEB_BASE_URL=https://attendance.yourchurch.org

SMTP_HOST=...        # see section 6
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=Church Attendance <no-reply@yourchurch.org>
```

- With `ENVIRONMENT=production` the server **refuses to start** if `SECRET_KEY` is short or
  starts with "change", and the `/docs` pages are switched off.
- Use a database user that only owns this database, not the `postgres` superuser.
- Never commit `.env`, and never put it in a zip you share.

## 3. First-time setup on the server

```
cd backend
python -m venv ../venv && ../venv/bin/pip install -r requirements.txt
../venv/bin/python -m scripts.init_db --church-name "Your Church" \
    --admin-name "Jane Doe" --admin-email jane@example.com \
    --admin-phone +237600000000 --admin-password 'a-strong-password'
../venv/bin/alembic upgrade head             # records the schema version
cd ../web && npm install && npm run build    # produces web/dist
```

## 4. Running the API and HTTPS

Run the API with **one worker** behind Caddy. The login rate limits are kept in the memory
of each worker, so more workers would multiply the allowed attempts.

`/etc/systemd/system/church-api.service`:

```
[Unit]
Description=Church Attendance API
After=network.target postgresql.service

[Service]
WorkingDirectory=/srv/church-attendance/backend
ExecStart=/srv/church-attendance/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
User=church

[Install]
WantedBy=multi-user.target
```

`--proxy-headers` makes the app see each visitor's real address, which the rate limiter needs.

`/etc/caddy/Caddyfile` (Caddy gets and renews the HTTPS certificate by itself):

```
attendance.yourchurch.org {
    encode gzip
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        root * /srv/church-attendance/web/dist
        try_files {path} /index.html
        file_server
    }
}
```

Then: `sudo systemctl enable --now church-api caddy`. Open only ports 80 and 443 in the
firewall; PostgreSQL (5432) and the API (8000) should not be reachable from outside.

## 4a. Check-in verification (location, then code or fingerprint)

Each service has **Check-in verification** (Admin > Services). When it is **On**, a member can only
check in (and clock out) from a phone that is at the church, and then confirms with ONE of:

- the **code** shown on the screen at church (or its QR code), or
- the **fingerprint, face or screen lock** of their own phone (see 4b).

Which of those a service accepts is its "How members confirm" setting: *Code only*, *Code or
fingerprint* (each member chooses; recommended) or *Fingerprint or face only* (no code).
A phone that is not at the church is always refused, whichever way the member confirms.

- **HTTPS is required in production.** Phones only share their location, and browsers only
  allow the phone-id storage, on `https://` pages. On plain `http://` nobody could check in,
  because every phone would be refused for not sharing a location.
- **Set the church location first:** stand inside the church, open Admin > Check-in and press
  "Use my current location", then Save. Until it is saved, the location check is skipped.
  Keep the radius at 150-300 m; phones are less accurate indoors. A member whose phone gives a
  position that is too rough to trust is asked to move near a window or outside and try again.
- **On the day:** Admin > Check-in > "Open check-in screen" on a projector or tablet (or the
  "Open check-in screen" link inside a session on the Attendance tab). Use the Full screen
  button. The code changes every 30 seconds and works for up to a minute. For *Fingerprint or
  face only* services the screen shows no code, only the QR code that opens the check-in.
- **The code is derived from `SECRET_KEY`.** If you change that key, codes already shown
  stop working; just refresh the check-in screen.
- **Check-ins that still get flagged** go through but appear under Admin > Check-in > Needs
  review: a phone that was not identified, or a second phone for an account (unless the member
  confirmed with their fingerprint). A wrong or expired code, or a phone away from the church,
  is always refused.
- **One phone can check in only one person per service.** Someone without a phone can be
  marked present by an admin from the Attendance tab.
- **Clock-out rules.** Members can only clock out once the service has ended, and only for
  3 hours after that. For services with verification On they must also be at the church, and
  whoever checked in with their fingerprint clocks out with it too. A service with **no end time**
  has nothing to wait for, so members can clock out whenever they like: set an end time on every
  service. Adjust with `CHECKOUT_OPENS_MINUTES_BEFORE_END` (default 0: exactly at the end) and
  `CHECKOUT_CLOSES_MINUTES_AFTER_END` (default 180) in the backend settings.
- The server must see each member's real address (the `--proxy-headers` option in section 4)
  for the address saved with each check-in to be meaningful.

### Printing attendance (PDF)

On the Attendance tab, pick a service (and a date range if you like) and press **Print PDF** on a
session. A PDF opens in a new tab: the church name, the service, its date and start and end
time, then everyone who attended in alphabetical order with phone, department(s) and clock in /
clock out times. Print or save it from the PDF viewer.

- The download link is signed and works for two minutes, for that one session and the admin who
  asked. Pop-up blockers may need to allow the new tab.
- It needs the `reportlab` package (`pip install -r requirements.txt`).
- Names with French accents print correctly. Letters outside Western European text (for
  example Cyrillic) are printed as "?".

## 4b. Fingerprint / face check-in (passkeys)

Members can set up their phone's fingerprint, face or screen lock on their Profile page.
A service can then accept it instead of the code, or require it (Admin > Services > How members
confirm), which stops someone checking in as a friend even if they know the friend's password.

- **Install the new dependencies:** `pip install -r requirements.txt` (adds `cryptography`,
  `Pillow` for profile photos and `reportlab` for PDFs).
- **The address must be right.** A passkey is tied to the website's domain. The app works
  out the domain from `WEB_BASE_URL`, so `WEB_BASE_URL` must be exactly the address people
  use, for example `https://attendance.yourchurch.org`. Passkeys need `https://`, except on
  `localhost`. If you ever **change the domain, every member's passkey stops working** and
  they must set it up again, so choose the domain before rolling this out. (Override with
  `WEBAUTHN_RP_ID` and `WEBAUTHN_ORIGINS` only if you serve the app from several addresses.)
- **Testing on your own computer:** open the app at `http://localhost:5173` (not
  `127.0.0.1` and not your network address) and keep `WEB_BASE_URL=http://localhost:5173`.
  Chrome will then offer Windows Hello, a PIN or a security key.
- **Testing on a phone:** phones need `https://`. Put the dev server behind a tunnel
  (for example `cloudflared` or `ngrok`), set `WEB_BASE_URL` to the tunnel address, restart the
  backend, and open the tunnel address on the phone. Vite may need `server: { allowedHosts: true }`
  in `web/vite.config.js` to accept the tunnel's hostname.
- **Rolling it out:** start services on "Code or fingerprint". Ask members to set it up while
  they are at church (an usher can watch). A member who has not set it up simply uses the code.
  The code stays available to everyone at that setting, so a friend at the church who knows a
  password could still use it: when most members have set up fingerprint check-in, switch the
  services where this matters to "Fingerprint or face only".
- **Who can change a passkey:** a member can add a second phone only by confirming with the
  first one. They cannot remove one. An admin removes them from Admin > Members > "Reset
  passkeys" (lost phone, or if you suspect someone set one up on another person's account).
- **The weak moment is the first set-up.** If a friend knows someone's password and sets up
  a passkey on that account before the owner does, the account is bound to the friend's
  phone. Setting up in person, and checking Admin > Members for who has one, closes that gap.
- Synced passkeys (iCloud Keychain, Google Password Manager) work and follow the member to a
  new phone signed in to the same account.

## 5. Database changes (migrations)

From now on, a change to a model is applied with Alembic instead of a hand-run script.
Run these from the `backend` folder:

```
alembic revision --autogenerate -m "describe the change"   # creates a file in alembic/versions
# open that file and check it does what you expect, then:
alembic upgrade head
alembic current                                              # shows the version in use
```

Always back up (section 7) before upgrading a live database. Autogenerate only suggests
changes; read each one before you apply it.

## 6. Email (password resets and approval notices)

If your host blocks SMTP (Render's free plan does), use `BREVO_API_KEY` or `RESEND_API_KEY`
instead; see "Email on Render" at the top of this guide. They work with `EMAIL_FROM` as the sender.

The app sends mail over SMTP. Pick any provider that gives you SMTP details: Brevo, Mailgun,
Amazon SES, Zoho, or a Gmail/Google Workspace account with an app password. Put the host,
port, user and password in `.env`.

- Port 587 with `SMTP_SECURITY=starttls` is the usual choice. Use 465 with `ssl` if the
  provider says so.
- For mail to reach inboxes instead of spam, send from an address on **your own domain** and
  add the SPF and DKIM records your provider tells you to.
- If email is not set up, the "Forgot password" page still answers, but nothing is sent.
  An admin can set a temporary password from Admin > Members instead.

## 7. Backups

```
cd backend
../venv/bin/python -m scripts.backup_db --keep 30
```

This writes a dated file in `backend/backups/` and removes older ones. It needs `pg_dump`
(package `postgresql-client`). Schedule it every night with cron (`crontab -e`):

```
0 2 * * *  cd /srv/church-attendance/backend && ../venv/bin/python -m scripts.backup_db --keep 30
```

- **Copy the backups off the server** (another machine, or cloud storage with `rclone`). A
  backup that sits on the same disk is lost with it.
- Also back up `backend/media/` (profile photos).
- **Test a restore** now and then on a spare database:
  `pg_restore --clean --if-exists --no-owner -d church_test backups/<file>.dump`

## 7a. Before you go live

- [ ] `ENVIRONMENT=production` and a long random `SECRET_KEY`
- [ ] HTTPS works and `http://` redirects to `https://`
- [ ] The admin account uses a strong password (not the one you used while testing)
- [ ] Sign in with a wrong password 6 times: you should be asked to wait
- [ ] Forgot password: the email arrives and the link works once
- [ ] A nightly backup runs, and you have restored one successfully
- [ ] Only ports 80 and 443 are open
