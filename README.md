
# Careers Monitor (Keyword Filtered)

Monitor hundreds of careers pages and alert to **Microsoft Teams** (via *Teams Workflows webhook*) and/or **email** when new roles appear. Supports **pagination** and ATS JSON feeds (Workday CXS, Greenhouse, Lever).

## Quick Start
1. Create a public GitHub repo and upload these files (preserve the folder paths).
2. Put your target URLs in `scraper/urls.csv`.
3. Leave `scraper/keywords.txt` empty to get all jobs.
4. Add a Teams **Workflows** webhook as a repo secret named `TEAMS_WEBHOOK_URL`.
5. Run the workflow from the **Actions** tab.

See inline comments in `scraper/config.yaml` and `.github/workflows/monitor.yml` to tweak settings.
