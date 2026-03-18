# Job Crawler (ML / Data Science)

This crawler scans company careers pages and returns role links relevant to:

- Machine Learning
- Data Science
- AI / Applied Scientist roles

It reads company targets from Supabase when configured, otherwise falls back to a JSON file, crawls each careers site, filters relevant jobs, and sends the results by email.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install
```

## Input Format

Use a JSON file like `companies.example.json` when seeding Supabase or when running without database-backed companies:

```json
{
  "companies": [
    { "name": "OpenAI", "careers_url": "https://openai.com/careers" },
    { "name": "Company B", "careers_url": "https://jobs.companyb.com" }
  ]
}
```


## Run

```bash
python crawler.py --companies companies.example.json
```

Optional flags:

- `--max-pages-per-company 20`
- `--timeout-seconds 15`
- `--max-age-days 2` (only keep jobs posted within the last N days; 0 disables)
- `--workers 5`
- `--location Germany --location Bengaluru` (keep only matching locations)
- `--send-email` (send the CSV results via Gmail SMTP)
- `--email-to someone@example.com` (repeatable, defaults to `GMAIL_USER`)
- `--email-subject "My Job Report"` (optional subject prefix)

## No-Args Defaults (GitHub Actions)

If you run `python crawler.py` with no args, defaults are pulled from:

- `job_crawler/config.py` (default locations and email settings)
- Supabase `companies` table if configured
- `companies.json` (fallback to `companies.example.json` if missing or Supabase has no enabled company rows)

Example for your use case:

```bash
python crawler.py --companies companies.example.json --location Germany --location Bengaluru
```

## Email (Gmail SMTP)

Set Gmail credentials as environment variables (or via `.env`):

```bash
setx GMAIL_USER "your.email@gmail.com"
setx GMAIL_APP_PASSWORD "your_app_password"
```


Optional `.env` file (same keys):

```
GMAIL_USER=your.email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SECRET_KEY=your_supabase_secret_key
SUPABASE_SENT_JOBS_TABLE=sent_jobs
SUPABASE_COMPANIES_TABLE=companies
JOB_CRAWLER_DEBUG=1
JOB_CRAWLER_DEBUG_FILE=debug.log
```

Then run:

```bash
python crawler.py --companies companies.example.json --location Germany --location Bengaluru --send-email --email-to you@example.com
```

## Output

- The crawler no longer writes job output files.
- Results are kept in memory and sent directly by email.
- When Supabase is configured, only jobs that have not already been emailed before for the same `company + title + job_id` are sent.
- If there are no new jobs, email is still sent with the message `No new jobs posted.`

## Supabase Deduplication

Create a table in Supabase for sent jobs:

```sql
create table if not exists public.sent_jobs (
  id bigint generated always as identity primary key,
  job_key text not null unique,
  company text not null,
  title text not null,
  job_id text not null default '',
  location text not null default '',
  job_url text not null default '',
  careers_url text not null default '',
  source text not null default '',
  posted_at timestamptz null,
  created_at timestamptz not null default now()
);
```

How it works:

- Before sending email, the crawler computes a fingerprint from normalized `company`, `title`, and `job_id`.
- If that fingerprint already exists in Supabase, the job is skipped.
- If the title is the same but the `job_id` is different, the fingerprint changes, so the job is treated as new and is emailed.
- Jobs are written to Supabase only after a successful email send.

Setup steps:

1. In Supabase, create the `sent_jobs` table using the SQL above.
2. In your local `.env`, add `SUPABASE_URL` and `SUPABASE_SECRET_KEY`.
3. In GitHub Actions, add repository secrets `SUPABASE_URL` and `SUPABASE_SECRET_KEY`.
4. Run the crawler once and confirm the first sent batch is inserted into `sent_jobs`.

Notes:

- Use the Supabase secret/service-role key only on the server side or in GitHub Actions. Do not expose it in frontend code.
- If Supabase is not configured, the crawler keeps the previous behavior and sends all matching jobs.
- If Supabase is temporarily unavailable, the run continues and logs the error, but duplicate emails may happen until the store is reachable again.

## Future Database Move

Company input can now come from a Supabase `companies` table. A good table shape is:

```sql
create table if not exists public.companies (
  id bigint generated always as identity primary key,
  company_key text not null unique,
  name text not null,
  careers_url text not null,
  enabled boolean not null default true,
  api_post jsonb null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

How it works:

- The crawler first tries to load enabled companies from Supabase.
- If Supabase is not configured, the table is empty, or loading fails, it falls back to `companies.json`.
- A temporary seed script is available at `sync_companies_to_supabase.py`.

To seed the table from JSON:

```bash
python sync_companies_to_supabase.py
```

This reads `companies.json` (or `companies.example.json` if needed) and inserts/updates rows in the Supabase `companies` table.

## Notes

- The crawler supports general HTML pages plus direct APIs for Greenhouse, Lever, Workday, Oracle ORC (best-effort), iCIMS, and SuccessFactors job boards.
- For Workday targets, `--location` uses Workday `appliedFacets` (server-side location filtering) when facet data is available.
- Playwright is used as a fallback when a company returns 0 jobs after filtering; it renders JavaScript pages to capture job links.
- If a company website blocks bots (HTTP 403), use that company's direct ATS URL (for example Greenhouse/Lever/Workday careers page) in your input list.
- The crawler attempts to auto-resolve known ATS links from a company careers page (Workday/Greenhouse/Lever) before crawling.

## Project Structure

- `crawler.py`: thin entrypoint
- `job_crawler/cli.py`: CLI argument parsing and orchestration
- `job_crawler/service.py`: `JobCrawlerService` class
- `job_crawler/providers/`: ATS-specific provider classes (`GreenhouseProvider`, `LeverProvider`, `WorkdayProvider`)
- `job_crawler/html_crawler.py`: generic HTML crawler
- `job_crawler/location.py`: location filter logic and aliases
- `job_crawler/io_utils.py`: input parsing and output writers
