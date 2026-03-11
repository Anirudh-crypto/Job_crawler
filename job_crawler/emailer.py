from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

import smtplib


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    sender: str
    recipients: list[str]


def load_gmail_config(recipients: list[str] | None) -> EmailConfig:
    smtp_user = os.environ.get("GMAIL_USER", "").strip()
    smtp_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not smtp_user or not smtp_password:
        raise ValueError(
            "Missing Gmail credentials. Set GMAIL_USER and GMAIL_APP_PASSWORD environment variables."
        )

    to_list = [item.strip() for item in (recipients or []) if item.strip()]
    if not to_list:
        to_list = [smtp_user]

    return EmailConfig(
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        sender=smtp_user,
        recipients=to_list,
    )


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def build_email_subject(prefix: str | None, total_jobs: int) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = prefix.strip() if prefix else "Job Crawler Results"
    return f"{title} - {total_jobs} jobs ({timestamp})"


def format_plain_text(rows: Iterable[dict[str, str]]) -> str:
    lines = ["Job Crawler Results", ""]
    for row in rows:
        lines.append(f"Company: {row.get('company','')}")
        lines.append(f"Title: {row.get('title','')}")
        lines.append(f"Location: {row.get('location','')}")
        lines.append(f"Job ID: {row.get('job_id','')}")
        lines.append(f"Careers URL: {row.get('careers_url','')}")
        lines.append(f"Source: {row.get('source','')}")
        lines.append("")
    if len(lines) == 2:
        lines.append("No jobs found.")
    return "\n".join(lines).rstrip()


def format_html(rows: Iterable[dict[str, str]]) -> str:
    header = """
    <html>
      <body style="font-family: Arial, sans-serif;">
        <h2>Job Crawler Results</h2>
        <table cellpadding="6" cellspacing="0" border="1" style="border-collapse: collapse;">
          <thead>
            <tr>
              <th align="left">Company</th>
              <th align="left">Title</th>
              <th align="left">Location</th>
              <th align="left">Job ID</th>
              <th align="left">Careers URL</th>
              <th align="left">Source</th>
            </tr>
          </thead>
          <tbody>
    """
    rows_html = []
    count = 0
    for row in rows:
        count += 1
        rows_html.append(
            "<tr>"
            f"<td>{row.get('company','')}</td>"
            f"<td>{row.get('title','')}</td>"
            f"<td>{row.get('location','')}</td>"
            f"<td>{row.get('job_id','')}</td>"
            f"<td>{row.get('careers_url','')}</td>"
            f"<td>{row.get('source','')}</td>"
            "</tr>"
        )
    if count == 0:
        rows_html.append(
            '<tr><td colspan="6" align="center">No jobs found.</td></tr>'
        )

    footer = """
          </tbody>
        </table>
      </body>
    </html>
    """
    return header + "\n".join(rows_html) + footer


def send_email_from_csv(
    csv_path: Path,
    subject_prefix: str | None,
    recipients: list[str] | None,
) -> None:
    rows = load_csv_rows(csv_path)
    subject = build_email_subject(subject_prefix, total_jobs=len(rows))
    text_body = format_plain_text(rows)
    html_body = format_html(rows)

    config = load_gmail_config(recipients)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port) as server:
        server.login(config.smtp_user, config.smtp_password)
        server.send_message(message)
