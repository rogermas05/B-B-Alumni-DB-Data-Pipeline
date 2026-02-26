# B@B Alumni LinkedIn Enrichment

Enriches a Slack member export with LinkedIn profile data (current title, company, education, etc.) using the Exa API.

## Setup

1. **Python 3** and a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip3 install -r requirements.txt
   ```

3. **API key:** Sign up at [exa.ai](https://exa.ai) and get an API key. Create a `.env` file in the project root:
   ```
   EXA_API_KEY=your_exa_api_key_here
   ```

4. **Input CSV:** Place your Slack export as `slack.csv` in the project root. Required columns: `fullname`, `email` (plus `username` helps for name disambiguation). Empty fullnames are skipped.

## How to Run

```bash
python3 enrich_linkedin.py
```

- Processes **10 people per run** (configurable via `BATCH_SIZE` in the script).
- First run copies `slack.csv` → `remaining.csv` and processes the first batch.
- Re-run to process the next 10.
- Results append to `enriched_linkedin.csv`.
- When done, `remaining.csv` will be empty and the script reports "All done!".

## Output

- `enriched_linkedin.csv` — Fullname, email, LinkedIn URL, current title/company, headline, location, education, B@B role/years.
- `enrichment_errors.log` — Logs for any lookup errors.

## Sensitive Data

`slack.csv`, `remaining.csv`, `enriched_linkedin.csv`, and `.env` contain PII and are gitignored. Do not commit them.
