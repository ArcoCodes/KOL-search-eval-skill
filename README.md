# KOL-search-eval-skill

KOL-search-eval-skill is a Codex skill for creator discovery, signal collection,
rough screening, and detailed evaluation across YouTube, TikTok, Instagram, and
Twitter/X.

The workflow is built around one practical goal: find creators who can actually
help with user acquisition, not just accounts with high follower counts. It
combines platform data, comment quality checks, audience-region inference,
pricing heuristics, and Feishu/Bitable writeback.

## What It Does

- Search creators by keyword, starting with YouTube discovery.
- Collect platform signals through dedicated scripts.
- Run rough screening for fraud, activity, engagement, and audience fit.
- Write qualified or rejected creators into a Feishu candidate pool.
- Reuse candidate-pool snapshots for detailed evaluation.
- Write detailed evaluation records, KOL hub rows, and optional Feishu IM notices.

## Workflow

```text
Search
  -> Signal collection
  -> Rough screening
  -> Candidate pool
  -> Human owner assignment
  -> Detailed evaluation
  -> KOL hub + evaluation record
```

Common entry points:

```bash
/kol search "AI video tools"
/kol @creator_handle
/kol https://www.youtube.com/@creator_handle
/kol eval https://www.youtube.com/@creator_handle
/kol check
```

## Repository Layout

| Path | Purpose |
|------|---------|
| `SKILL.md` | Codex skill instructions and routing logic |
| `scripts/yt_search.py` | YouTube creator discovery |
| `scripts/data_scrawl/` | Platform signal collection for YouTube, TikTok, Instagram, Twitter/X |
| `scripts/write_candidate.py` | Candidate-pool writeback after rough screening |
| `scripts/check_kol_exists.py` | Existing KOL/candidate lookup before detailed evaluation |
| `scripts/write_kol.py` | Detailed evaluation writeback |
| `scripts/sync_hub.py` | KOL hub aggregation sync |
| `scripts/feishu_notify.py` | Optional Feishu IM notification |
| `references/` | Evaluation rules, methodology, schema notes, tag taxonomy, anti-fraud references |
| `docs/kol-reports/` | Example KOL reports |

## Dependencies

| Dependency | Install | Purpose |
|------------|---------|---------|
| Python 3 | System built-in or `brew install python` | Evaluation scripts |
| yt-dlp | `brew install yt-dlp` | Primary YouTube data fetching |
| lark-cli | `npm install -g lark-cli` | Feishu Bitable read/write |
| requests | `pip3 install requests` | HTTP requests used by scripts |
| yt-dlp Python module | `pip3 install yt-dlp` | Optional Python import path for some collection flows |

## Configuration

Create `scripts/.env`:

```dotenv
TIKHUB_API_KEY=your_api_key_here
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxx
```

Environment variables can also be exported directly in your shell. The scripts
first read the shell environment, then fall back to `scripts/.env`.

| Variable | Required For | Notes |
|----------|--------------|-------|
| `TIKHUB_API_KEY` | TikTok, Instagram, Twitter/X, and YouTube fallback | YouTube uses yt-dlp first; TikHub is used when yt-dlp is rate-limited or for non-YouTube platforms |
| `FEISHU_APP_ID` | Feishu IM notification and app-token flows | Required by `scripts/feishu_notify.py` |
| `FEISHU_APP_SECRET` | Feishu IM notification and app-token flows | Required by `scripts/feishu_notify.py` |

Do not commit `scripts/.env` or any other `.env` file. This repository's
`.gitignore` excludes environment files by default.

## TikHub Billing Notes

- YouTube: yt-dlp is the primary source and is free. TikHub is the fallback when
  rate-limited or when extra TikHub-only data is needed.
- Instagram, TikTok, and Twitter/X: TikHub is the required source, so API calls
  are billed.
- TikHub rate limiting is handled inside the scripts at roughly 8 RPS per
  process. If future batch jobs use multiple processes, add a shared limiter.

## Verification

Run:

```bash
/kol check
```

Or manually verify the environment:

```bash
command -v python3 && python3 --version
command -v yt-dlp && yt-dlp --version
command -v lark-cli && echo "lark-cli OK"
python3 -c "import requests; print('requests OK')"
python3 -c "import yt_dlp; print('yt_dlp module OK')"
grep -q TIKHUB_API_KEY scripts/.env && echo "TIKHUB_API_KEY configured"
grep -q FEISHU_APP_ID scripts/.env && echo "FEISHU_APP_ID configured"
grep -q FEISHU_APP_SECRET scripts/.env && echo "FEISHU_APP_SECRET configured"
```

Script import smoke test:

```bash
cd scripts
python3 -c "import tikhub; print('tikhub OK')"
python3 data_scrawl/youtube_data.py --help
```

Feishu access check:

```bash
lark-cli api GET /open-apis/bitable/v1/apps/WEcDbjFnKa48YbsKa8qc8auQnlc/tables --jq '.data.total'
```

## Troubleshooting

- `yt-dlp` fails: update with `brew upgrade yt-dlp`. YouTube changes frequently.
- YouTube asks for sign-in or bot verification: pause heavy comment scraping, or
  use `yt-dlp --cookies-from-browser chrome` when appropriate.
- `lark-cli` auth expires: re-run `lark-cli` and refresh credentials.
- TikHub returns 403: check API key validity and account balance in the TikHub
  dashboard.
- TikTok, Instagram, or Twitter/X collection fails immediately: confirm
  `TIKHUB_API_KEY` is configured in `scripts/.env` or the shell environment.

## Reference Documents

| File | Purpose |
|------|---------|
| `references/process.md` | End-to-end KOL evaluation and writeback process |
| `references/business-standards.md` | Business-line scoring standards and CPM references |
| `references/methodology.md` | Evaluation methodology, anti-fraud signals, pricing logic |
| `references/rough-eval-rules.md` | Rough screening rules |
| `references/detailed-eval-rules.md` | Detailed evaluation rules |
| `references/tag-taxonomy.md` | Controlled vocabulary for content tags |
| `references/fraud-detection.md` | Fraud-detection notes and correlation checks |
| `references/DB-schema.md` | Feishu/Bitable schema notes |
