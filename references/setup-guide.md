# KOL Skill Setup Guide

## Dependencies

| Dependency | Install | Purpose |
|------------|---------|---------|
| Python 3 | System built-in | All evaluation scripts |
| yt-dlp | `brew install yt-dlp` | YouTube data fetching (free tier) |
| lark-cli | `npm install -g lark-cli` | Feishu bitable read/write |
| requests | `pip3 install requests` | HTTP requests (used internally by scripts) |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TIKHUB_API_KEY` | TikHub API — YouTube fallback + IG/TikTok/Twitter required |

### Configuration

Create `scripts/.env` with:

```
TIKHUB_API_KEY=your_api_key_here
```

The scripts load this file automatically via `dotenv`.

## TikHub Billing Notes

- **YouTube**: yt-dlp is the primary source (free). TikHub is the fallback when rate-limited.
- **Instagram / TikTok / Twitter**: TikHub is the only source — each API call is billed.

## Verification

Run `/kol check` to verify all dependencies, or manually:

```bash
command -v python3 && python3 --version
command -v yt-dlp && yt-dlp --version
command -v lark-cli && echo "lark-cli OK"
python3 -c "import requests; print('requests OK')"
grep -q TIKHUB_API_KEY scripts/.env && echo "TIKHUB_API_KEY configured"
```

### Script Import Test

```bash
cd scripts
python3 -c "import tikhub; print('tikhub OK')"
python3 data_scrawl/youtube_data.py --help
```

## Troubleshooting

- **yt-dlp fails:** Update with `brew upgrade yt-dlp` — YouTube frequently changes their API
- **lark-cli auth expired:** Re-run `lark-cli` to refresh tokens
- **TikHub 403:** Check API key validity and balance at TikHub dashboard
