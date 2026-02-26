#!/Users/rogermas/Berkeley/B@B/Alumni Database Automation/venv/bin/python3.13
"""
LinkedIn Enrichment Script for B@B Slack Export
Finds LinkedIn profiles via Exa API and extracts professional info.
Processes 10 people per run. Re-run to do the next batch.
"""

import csv
import os
import re
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from exa_py import Exa

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(SCRIPT_DIR, "slack.csv")
REMAINING_CSV = os.path.join(SCRIPT_DIR, "remaining.csv")
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "enriched_linkedin.csv")
ERROR_LOG = os.path.join(SCRIPT_DIR, "enrichment_errors.log")
BATCH_SIZE = 10
RATE_LIMIT_DELAY = 1.0

OUTPUT_FIELDS = [
    "fullname", "email", "linkedin_url", "current_title",
    "current_company", "linkedin_headline", "location", "education",
    "bab_role", "bab_years",
]


def init_remaining():
    """Copy slack.csv to remaining.csv on first run, filtering out empty names."""
    with open(INPUT_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = [r for r in reader if r.get("fullname", "").strip()]

    with open(REMAINING_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return rows, fieldnames


def read_remaining():
    """Read the remaining.csv file."""
    with open(REMAINING_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return rows, fieldnames


def write_remaining(rows, fieldnames):
    """Rewrite remaining.csv without the processed rows."""
    with open(REMAINING_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_result(row_dict):
    """Append a single row to the output CSV."""
    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writerow(row_dict)


def log_error(email, fullname, error_msg):
    with open(ERROR_LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {fullname} ({email}): {error_msg}\n")


def guess_fullname(row):
    """Try to build a better full name from slack data when fullname is a single word."""
    fullname = row.get("fullname", "").strip()
    if " " in fullname:
        return fullname

    # Try to extract last name from username or email
    username = row.get("username", "").strip()
    email = row.get("email", "").strip()
    email_prefix = email.split("@")[0] if email else ""

    # Common pattern: email like "lelandlee4@gmail.com" -> "Leland Lee"
    # Try matching first name at start of email prefix
    first_lower = fullname.lower()
    for source in [email_prefix, username]:
        source_lower = source.lower().rstrip("0123456789")
        if source_lower.startswith(first_lower) and len(source_lower) > len(first_lower):
            rest = source_lower[len(first_lower):]
            if rest.isalpha() and len(rest) > 1:
                return f"{fullname} {rest.capitalize()}"

    # Try username as last name (e.g. username=nihalani, fullname=Ashvin)
    if username and username.lower() != first_lower and username.isalpha() and len(username) > 2:
        return f"{fullname} {username.capitalize()}"

    return fullname


def parse_linkedin_text(text):
    """Extract structured info from LinkedIn profile text."""
    empty = {
        "current_title": "", "current_company": "", "linkedin_headline": "",
        "location": "", "education": "", "bab_role": "", "bab_years": "",
    }
    if not text:
        return empty

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # Headline: 2nd non-empty line (after the name)
    headline = lines[1] if len(lines) > 1 else ""

    # Extract current title + company from Experience section
    current_title = ""
    current_company = ""

    # First try to find a role marked (Current)
    current_match = re.search(
        r"###\s+(.+?)\s+at\s+(?:\[([^\]]+)\](?:<[^>]*>|\([^)]*\))|([^\n(]+))\s*\(Current\)",
        text
    )
    if not current_match:
        # Fall back to first role under ## Experience
        exp_pos = text.find("## Experience")
        if exp_pos != -1:
            exp_text = text[exp_pos:]
            current_match = re.search(
                r"###\s+(.+?)\s+at\s+(?:\[([^\]]+)\](?:<[^>]*>|\([^)]*\))|([^\n(]+))",
                exp_text
            )

    if current_match:
        current_title = current_match.group(1).strip()
        current_company = (current_match.group(2) or current_match.group(3) or "").strip()
        current_company = re.sub(r"\s*\(Current\)\s*$", "", current_company).strip()

    # Location: LinkedIn format is "City, State, Country (XX)" before connections line
    location = ""
    for line in lines[2:6]:
        if re.search(r"connections|followers", line, re.IGNORECASE):
            break
        if re.search(r"\([A-Z]{2}\)\s*$", line):
            location = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", line).strip()
            break
        if re.match(r"^[A-Z][a-z]+.*,\s*[A-Z]", line) and "at " not in line and "##" not in line:
            location = line.strip()
            break

    education = "UC Berkeley" if "berkeley" in text.lower() else ""

    # Extract B@B role and years from experience
    # LinkedIn text has blank lines between ### header and date, so use \s* to bridge them
    bab_role = ""
    bab_years = ""
    bab_matches = re.findall(
        r"###\s+(.+?)\s+at\s+(?:\[)?Blockchain at Berkeley(?:\])?(?:<[^>]*>|\([^)]*\))?"
        r"[\s\S]*?(\w+\s+\d{4})\s*-\s*((?:\w+\s+\d{4})|Present)",
        text
    )
    if bab_matches:
        # Use the earliest B@B role (first chronologically = last in list)
        roles = []
        for role, start, end in bab_matches:
            roles.append(role.strip())
        bab_role = " / ".join(roles)
        # Date range: earliest start to latest end
        bab_years = f"{bab_matches[-1][1]} - {bab_matches[0][2]}"

    return {
        "current_title": current_title,
        "current_company": current_company,
        "linkedin_headline": headline,
        "location": location,
        "education": education,
        "bab_role": bab_role,
        "bab_years": bab_years,
    }


def name_matches(fullname, title, url=""):
    """Check if the person's name appears in the LinkedIn result title or URL."""
    name_parts = fullname.lower().split()
    title_lower = title.lower() if title else ""
    url_lower = url.lower() if url else ""
    first = name_parts[0] if name_parts else ""
    last = name_parts[-1] if len(name_parts) > 1 else ""

    first_in = first in title_lower
    # Last name can match in title OR in URL slug (handles "Ashvin N." with url /ashvinnihalani)
    last_in = not last or last in title_lower or last in url_lower
    return first_in and last_in


def search_linkedin(exa, fullname, row):
    """Search for a person's LinkedIn profile using Exa API."""
    search_name = guess_fullname(row) if " " not in fullname else fullname
    query = f"{search_name} Berkeley"

    result = exa.search_and_contents(
        query,
        num_results=5,
        category="people",
        include_domains=["linkedin.com"],
        text={"include_html_tags": False, "max_characters": 10000},
    )

    # Filter to results that match the name
    matches = [r for r in result.results if name_matches(search_name, r.title, r.url)]
    if not matches:
        return None, None

    # Prefer matches that mention "berkeley" in their profile text (more likely the right person)
    berkeley_matches = [r for r in matches if r.text and "berkeley" in r.text.lower()]
    best = berkeley_matches[0] if berkeley_matches else matches[0]

    text = best.text
    # If text is truncated (no Experience section), try get_contents as fallback
    if text and "## Experience" not in text:
        try:
            for m in ([best] + [r for r in matches if r != best]):
                content = exa.get_contents(
                    [m.url],
                    text={"include_html_tags": False, "max_characters": 10000},
                )
                if content.results and content.results[0].text and "## Experience" in content.results[0].text:
                    text = content.results[0].text
                    break
        except Exception:
            pass

    return best.url, text


def search_bab_web(exa, fullname):
    """Search the web for B@B role info when LinkedIn doesn't have it."""
    try:
        result = exa.search_and_contents(
            f'"{fullname}" "Blockchain at Berkeley"',
            num_results=3,
            text={"include_html_tags": False, "max_characters": 2000},
        )
        for r in result.results:
            text = (r.text or "").lower()
            if fullname.lower().split()[0] in text and "blockchain at berkeley" in text:
                # Try to extract role from context
                raw = r.text or ""
                # Look for patterns like "Editor of Blockchain at Berkeley" or role mentions
                role_match = re.search(
                    r"(?:(\w[\w\s]+?)\s+(?:of|at|for)\s+)?Blockchain at Berkeley",
                    raw, re.IGNORECASE
                )
                role = ""
                if role_match and role_match.group(1):
                    role = role_match.group(1).strip()
                    # Filter out generic words
                    if role.lower() in ("member", "the", "about", "from", "and", "with"):
                        role = ""
                return role or "Member", ""
    except Exception:
        pass
    return "", ""


def empty_row(fullname, email):
    return {f: "" for f in OUTPUT_FIELDS} | {"fullname": fullname, "email": email}


def main():
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

    api_key = os.environ.get("EXA_API_KEY")
    if not api_key or api_key == "your_exa_api_key_here":
        print("ERROR: Set your EXA_API_KEY in the .env file.")
        sys.exit(1)

    exa = Exa(api_key=api_key)

    # First run: create remaining.csv from slack.csv
    if not os.path.exists(REMAINING_CSV):
        rows, fieldnames = init_remaining()
        print(f"Created remaining.csv with {len(rows)} people (filtered empty names).")
    else:
        rows, fieldnames = read_remaining()

    total_remaining = len(rows)
    if total_remaining == 0:
        print("All done! No one left in remaining.csv.")
        return

    # Create output CSV header if it doesn't exist
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()

    batch = rows[:BATCH_SIZE]
    print(f"Processing batch of {len(batch)} (out of {total_remaining} remaining)...")

    found = 0
    errors = 0

    for i, row in enumerate(batch):
        fullname = row.get("fullname", "").strip()
        email = row.get("email", "").strip()
        search_name = guess_fullname(row) if " " not in fullname else fullname
        display = f"{search_name} ({email})" if search_name != fullname else f"{fullname} ({email})"
        print(f"  [{i+1}/{len(batch)}] {display}...", end=" ", flush=True)

        try:
            url, text = search_linkedin(exa, fullname, row)
            if url:
                parsed = parse_linkedin_text(text)
                append_result({"fullname": fullname, "email": email, "linkedin_url": url, **parsed})
                found += 1
                print(f"Found: {url}")
            else:
                append_result(empty_row(fullname, email))
                errors += 1
                print("Not found")
        except Exception as e:
            log_error(email, fullname, str(e))
            append_result(empty_row(fullname, email))
            errors += 1
            print(f"Error: {e}")

        if i < len(batch) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    # Remove processed batch from remaining.csv
    remaining_after = rows[BATCH_SIZE:]
    write_remaining(remaining_after, fieldnames)

    print(f"\nBatch complete! Found: {found}, Not found/errors: {errors}")
    print(f"Remaining: {len(remaining_after)} people")
    print(f"Results appended to: {OUTPUT_CSV}")
    if len(remaining_after) > 0:
        print(f"Run again to process the next {min(BATCH_SIZE, len(remaining_after))}.")


if __name__ == "__main__":
    main()
