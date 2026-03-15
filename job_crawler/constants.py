USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "source",
    "ref",
    "referrer",
}

RELEVANT_PHRASES = [
    "machine learning",
    "ml engineer",
    "data science",
    "data scientist",
    "applied scientist",
    "artificial intelligence",
    "ai engineer",
    "deep learning",
    "computer vision",
    "nlp",
    "natural language processing",
    "llm",
    "research scientist",
    "analytics engineer",
    "data analyst",
    "generative ai",
    "genai",
    "mle",
]

ROLE_WORDS = [
    "engineer",
    "scientist",
    "analyst",
    "researcher",
    "manager",
    "director",
    "architect",
    "intern",
    "specialist",
    "developer",
    "lead",
    "principal",
    "staff",
    "head",
    "consultant",
]

JOB_CUE_PHRASES = [
    "careers",
    "jobs",
    "openings",
    "positions",
    "requisition",
    "req id",
    "vacancy",
    "apply",
    "role",
]

ALLOWED_SCHEMES = {"http", "https"}

KNOWN_JOB_HOST_MARKERS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workday.com",
    "smartrecruiters.com",
    "ashbyhq.com",
    "jobvite.com",
    "icims.com",
    "oraclecloud.com",
    "careers.oracle.com",
    "jobs.sap.com",
    "successfactors.com",
)

# Keys and values are normalized with normalize_text.
LOCATION_ALIASES: dict[str, list[str]] = {
    "germany": ["germany", "deutschland"],
    "deutschland": ["germany", "deutschland"],
    "bengaluru": [
        "bengaluru",
        "bangalore",
        "bengaluru india",
        "bangalore india",
        "india bengaluru",
        "india bangalore",
    ],
    "bangalore": [
        "bengaluru",
        "bangalore",
        "bengaluru india",
        "bangalore india",
        "india bengaluru",
        "india bangalore",
    ],
    "bengaluru india": [
        "bengaluru",
        "bangalore",
        "bengaluru india",
        "bangalore india",
        "india bengaluru",
        "india bangalore",
    ],
}
