# Job Crawler (ML / Data Science)

This crawler scans company careers pages and returns role links relevant to:

- Machine Learning
- Data Science
- AI / Applied Scientist roles

It reads a company list JSON file, crawls each careers site, filters relevant jobs, and writes results to:

- `jobs.csv`
- `jobs.md`

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Input Format

Use a JSON file like `companies.example.json`:

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
python crawler.py --companies companies.example.json --output-csv jobs.csv --output-md jobs.md
```

Optional flags:

- `--max-pages-per-company 20`
- `--timeout-seconds 15`
- `--workers 5`
- `--location Germany --location Bengaluru` (keep only matching locations)
- `--send-email` (send the CSV results via Gmail SMTP)
- `--email-to someone@example.com` (repeatable, defaults to `GMAIL_USER`)
- `--email-subject "My Job Report"` (optional subject prefix)

Example for your use case:

```bash
python crawler.py --companies companies.example.json --output-csv jobs.csv --output-md jobs.md --location Germany --location Bengaluru
```

## Email (Gmail SMTP)

Set Gmail credentials as environment variables:

```bash
setx GMAIL_USER "your.email@gmail.com"
setx GMAIL_APP_PASSWORD "your_app_password"
```

Then run:

```bash
python crawler.py --companies companies.example.json --output-csv jobs.csv --output-md jobs.md --location Germany --location Bengaluru --send-email --email-to you@example.com
```

## Output

- `jobs.csv`: machine-readable list with `company,title,location,job_id,careers_url,source`
- `jobs.md`: grouped markdown list of links

## Notes

- The crawler supports general HTML pages plus direct APIs for Greenhouse, Lever, and Workday links.
- For Workday targets, `--location` uses Workday `appliedFacets` (server-side location filtering) when facet data is available.
- Some careers pages are heavily JavaScript-rendered and may need a browser-based crawler (Playwright/Selenium) for full coverage.
- If a company website blocks bots (HTTP 403), use that company's direct ATS URL (for example Greenhouse/Lever/Workday careers page) in your input list.

## Project Structure

- `crawler.py`: thin entrypoint
- `job_crawler/cli.py`: CLI argument parsing and orchestration
- `job_crawler/service.py`: `JobCrawlerService` class
- `job_crawler/providers/`: ATS-specific provider classes (`GreenhouseProvider`, `LeverProvider`, `WorkdayProvider`)
- `job_crawler/html_crawler.py`: generic HTML crawler
- `job_crawler/location.py`: location filter logic and aliases
- `job_crawler/io_utils.py`: input parsing and output writers
