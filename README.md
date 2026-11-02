# Competitor Pricing & Strategy Tracker

A FastAPI application for tracking public competitor pricing pages. It captures page text and optional screenshots, extracts plan and feature information, records changes between successful scans, and generates Markdown and PDF reports.

![screenshots](screenshots/diagram.png)


## Features

- User registration and login, with a separate workspace created for each new account.
- Workspace-scoped competitor, page, scan, pricing, event, screenshot, and report data.
- Manual scans of configured public web pages.
- HTTP fetching with robots.txt checks, redirect revalidation, retry limits, response-size checking, and public-address URL validation.
- Rule-based extraction of plan names, displayed prices, currencies, billing intervals, billing basis, and list-item features.
- Change events for new or removed plans, price changes, feature statements, and pages that could not be captured.
- Optional screenshots and visual comparisons between successful captures.
- Product-profile feature comparison in generated reports.
- Markdown and PDF report downloads.

## Requirements

For local development, use Python 3.10 or later and pip. Dependencies are listed in `requirements.txt`. Chromium is needed for screenshot capture; the Docker image is based on the Playwright Python image, which includes browser support.

## Run locally

From the repository root, create and activate a virtual environment, install the project dependencies, install Playwright's Chromium browser, and start the development server:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On macOS or Linux, activate the virtual environment with:

```sh
source .venv/bin/activate
```

Open `http://127.0.0.1:8000` in a browser. The application serves its frontend from `static/` and its API under `/api/v1`.

## Run with Docker

Build the image from the repository root:

```sh
docker build -t competitor-tracker .
```

Run it with persistent storage for the SQLite database and generated files:

```sh
docker run --name competitor-tracker \
  -p 8000:8000 \
  -v competitor-tracker-data:/data \
  competitor-tracker
```

Open `http://localhost:8000`. The container stores its database and generated screenshots/reports under `/data`; mount a persistent volume there to keep data across container replacement. To stop it, run `docker stop competitor-tracker`.

## Configuration and data

- `DATA_DIR`: directory for `tracker.db`, screenshots, visual diffs, and generated PDF reports. Defaults to `data`; the Dockerfile sets it to `/data`.
- `ALLOW_PRIVATE`: when set to `1`, URL validation allows private and loopback addresses. This exists for local tests and the synthetic demo. **Do not set it in a production deployment.**

The tests configure `DATA_DIR` to a temporary directory and enable `ALLOW_PRIVATE` because their local fixture server binds to loopback. Keep secrets and production-specific settings outside the image and source control.

## Use the application

1. Open the web interface and register an account.
2. Add a competitor with a publicly reachable website URL.
3. Add a monitored page belonging to that competitor. The URL must pass the application's HTTP/HTTPS and public-address validation.
4. Run a scan from the interface. Scans are currently manual; a monitoring interval is stored but not scheduled.
5. Review extracted pricing, snapshots, change events, and visual diffs.
6. Optionally enter your own product's feature statements in the product profile, then generate a report.

The extractor currently recognizes plan/tier page elements when an element's class contains `plan` or `tier` and it contains a heading (`h2`, `h3`, or `h4`). List items within the plan element are treated as feature statements. Websites using other markup may not be parsed usefully.

## API overview

All API routes use the `/api/v1` prefix. Register or log in to obtain a token. For typical API requests, pass it in the `Authorization` header:

```http
Authorization: Bearer YOUR_TOKEN
```

The frontend also uses query-string tokens for some image/PDF requests. Query-string tokens can be exposed in browser history, logs, or referrer data; prefer the authorization header in API clients where supported.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Create an account and workspace; returns a session token. |
| `POST` | `/auth/login` | Authenticate and return a session token. |
| `GET`, `POST` | `/competitors` | List or add competitors in the current workspace. |
| `GET`, `POST` | `/monitored-pages` | List pages or add a page for a workspace competitor. |
| `POST` | `/monitored-pages/{page_id}/scan` | Run a scan; `shots=false` skips screenshot capture. |
| `GET` | `/snapshots` | List captures and capture statuses. |
| `GET` | `/pricing` | Return extracted pricing for each page's latest successful snapshot. |
| `GET` | `/change-events` | List events; optional `event_type` query filter. |
| `GET` | `/jobs` | List scan jobs. |
| `GET` | `/visual-diffs` | List screenshot comparison metadata. |
| `GET` | `/snapshots/{snapshot_id}/screenshot` | Retrieve a stored screenshot. |
| `GET` | `/visual-diffs/{diff_id}/image` | Retrieve a visual-diff image. |
| `GET`, `PUT` | `/product-profile` | Read or update the workspace product profile. |
| `POST`, `GET` | `/reports` | Generate a report or list generated reports. |
| `GET` | `/reports/{report_id}/markdown` | Download a report as Markdown. |
| `GET` | `/reports/{report_id}/pdf` | Generate and download a report as PDF. |

Interactive API documentation is available at `/docs` while the application is running.

### Example API flow

Create an account:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@example.com","password":"change-this-password"}'
```

Use the returned token to create a competitor and monitored page, replacing `TOKEN` and the sample URLs as needed:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/competitors \
  -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Example competitor","website_url":"https://example.com"}'

curl -X POST http://127.0.0.1:8000/api/v1/monitored-pages \
  -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"competitor_id":1,"url":"https://example.com/pricing"}'

curl -X POST 'http://127.0.0.1:8000/api/v1/monitored-pages/1/scan?shots=false' \
  -H 'Authorization: Bearer TOKEN'
```

IDs are workspace-specific database IDs, so use the IDs returned by your own API calls rather than assuming the example values.

## Run tests and demo

Run the automated test suite from the repository root:

```sh
python -m pytest -q
```

The tests cover authentication basics, workspace isolation, URL validation, extraction, change detection, visual-diff calculations, and end-to-end API flows using local synthetic pages. The current suite contains 39 tests; tests may evolve as the project changes.

Run the demo to launch a local synthetic competitor site and application, scan the fixtures, generate a report, and write UI screenshots into `screenshots/`:

```sh
python scripts/demo.py
```

The demo requires the project dependencies and Playwright Chromium. It is intended for local evaluation, not deployment.

## Project layout

```text
app/                 FastAPI routes, database helpers, scanner, extraction, safety, and reporting
fixtures/            Synthetic pricing pages and a local fixture server
scripts/demo.py      End-to-end local demonstration
static/              Browser-based application interface
tests/               Pytest unit and API tests
Dockerfile           Container image definition
requirements.txt     Python dependencies
data/                Default local database and generated artifacts directory
screenshots/         Demo-generated UI screenshots
```

## Security notes

- Only HTTP and HTTPS URLs without embedded credentials are accepted.
- URL validation rejects addresses that are not globally routable unless `ALLOW_PRIVATE=1` is set.
- Redirect destinations and browser subrequests are revalidated to reduce server-side request forgery (SSRF) risk.
- Configure this application behind an appropriately secured network boundary before exposing it publicly. It does not include a production deployment hardening profile.
- Session tokens do not expire or have a revocation endpoint in the current implementation. The frontend stores its token in `localStorage`.
- `ALLOW_PRIVATE=1` bypasses the private-address restriction and must remain limited to tests or isolated local demos.

## Known limitations

- The project uses SQLite and runs scans synchronously on request. There is no background queue or scheduler.
- `monitoring_interval_minutes` is stored but not used to schedule scans.
- A scan does not follow a browser-based JavaScript-only extraction strategy. Its extraction is rule-based and depends on the page's HTML structure.
- Price parsing supports a limited set of symbols and textual patterns. Uncertain or unsupported values should be manually reviewed.
- The page fetch enforces a response-size limit after the response body is read, rather than during streaming.
- Screenshots are optional context and may fail independently of text/pricing extraction. Visual changes can reflect layout or rendering noise rather than a meaningful product change.
- Feature statements disappearing from a page are not proof that the feature was discontinued.
- The report's product-profile comparison is a simple text comparison, not semantic analysis.
- There are no email or chat notifications, password reset, member-invitation workflow, or competitor edit/archive API in this MVP.
- Session tokens are long-lived, and query-string authentication for media/report routes has weaker exposure characteristics than header-based authentication.
- Tests use synthetic pages; validate behavior on permitted target sites before relying on results.

## Troubleshooting

**Screenshots fail but scans complete:** run `python -m playwright install chromium` for local development and inspect the scan's snapshot record. Screenshot capture is best-effort and does not determine whether the text scan succeeds.

**A page is rejected:** verify its URL uses HTTP or HTTPS, has no embedded username/password, resolves to public IP addresses, and is not blocked by the target site's robots.txt policy.

**Pricing is missing or inaccurate:** inspect the site's HTML structure and compare it with the supported plan/tier selectors. Unsupported markup or unfamiliar price formats may require extractor changes and additional tests.

**Local fixture URLs fail in a manual test:** private/loopback targets are blocked by default. The test suite and demo set `ALLOW_PRIVATE=1` for their local synthetic server; do not use that setting on a public deployment.

**The database appears empty after a container restart:** confirm that a persistent volume is mounted at `/data` and that the container is using the same volume.

## License

No license file is currently included. Add the license terms that apply to this project before distributing it.
