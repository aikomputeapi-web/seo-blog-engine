# seo-blog-engine

Autonomous, competitor-following SEO blog writer for a fleet of small single-tool websites.

Each registered tool website gets daily blog research based on its configured competitors: the engine harvests competitor blogs, normalizes and clusters topics by how many competitors cover them, screens new topics, writes SEO-structured articles, and publishes them straight into each site's repo (commit + push, or wrangler deploy).

## How it works

1. **Registry** (`data/sites.json`) - every tool site: name, tool URL, repo, blog content dir, keywords, tracked competitors, and a log of published articles.
2. **Research** (`engine/competitors.py`) - pulls each competitor's `sitemap.xml` (robots.txt fallback + blog-page probing), filters index/assets and irrelevant posts, scrapes article metadata concurrently, and caches per day in `data/research/<site>/`.
3. **Topics** (`engine/topics.py`) - normalizes article titles into canonical topics and clusters them by distinct-domain coverage. Topics covered by 2+ competitors get priority; fresh single-source topics are screened and checked against the registered tool capabilities.
4. **Writer** (`engine/writer.py`) - builds a research-driven prompt (competitor samples, already-published guard, keyword-first title/meta/H2/FAQ structure), avoids claiming unregistered tool features, sanity-gates the draft (word count, H2 count, no fences), and retries once with corrective feedback.
5. **Publisher** (`engine/publisher.py`) - writes the article into the site repo, commits, pushes.
6. **Autonomy** (`daily-loop.ps1`, `daily-run.ps1`, and Startup `seo-blog-engine-daily.vbs`) - a hidden resident process checks every 15 minutes and runs at/after 9:00 AM local time. It catches up at sign-in if the computer missed the scheduled time. An exclusive lock and once-per-day state guard prevent duplicate runs. Logs to `logs/scheduled-YYYY-MM-DD.log`.

## CLI (run from this folder)

| Command | What it does |
| --- | --- |
| `python -m engine.cli addsite --key K --name N --url U --repo R --dir D --description "..." --keywords "a,b,c"` | Register a tool website (D = blog content dir inside the site repo) |
| `python -m engine.cli research --site K [--discover]` | Harvest tracked competitors' blogs (cached per day) |
| `python -m engine.cli report [--site K]` | Topic coverage report: evergreen vs fresh, what gets picked |
| `python -m engine.cli run [--site K] [--max N] [--no-push]` | Full cycle: harvest, cluster, pick, write, publish |
| `python -m engine.cli loop --every-hours H` | Resident continuous daemon |

## Adding a website

```
python -m engine.cli addsite --key mp3-converter --name "FreeMP3" --url https://your-site.example --repo C:\path\to\site-repo --dir src/content/blog --description "Free in-browser MP3 converter" --keywords "mp3 converter, convert to mp3, audio converter"
```

Competitor discovery via search engines is IP-blocked in this environment, so seed `competitors` in `data/sites.json` with 4-6 real rivals (from a websearch at registration time) - the engine takes it from there. The daily cycle discovers their new articles automatically via sitemaps.

## Kaleido pilot

Kaleido is registered as `kaleido` and published at <https://aikomputeapi-web.github.io/convert/>. Its initial guide is at <https://aikomputeapi-web.github.io/convert/blog/file-conversion-guide/>. On 2026-10-08, the crawler collected 20 relevant posts from four of the five configured converter blogs; no subject appeared on two or more sources, so the sample did not establish a majority topic. The starter guide came from one source and should be treated as an onboarding guide, not a competitor consensus.

Competitor sources are a manually seeded list. The engine measures what those sources publish and their topic overlap; it does not measure search rankings, organic traffic, or backlinks, so it cannot independently identify traffic-leading competitors.

## LLM

Uses the OpenCode-authenticated Zen router (`https://zen.nowrouter.store/v1`) with free models only. It reads `OPENCODE_ZEN_API_KEY` from the machine environment; the key is never stored in this repository. The default model is `longcat-2.5-preview-free`, with two free-model fallbacks. Set `BLOGENGINE_LLM_URL` or `BLOGENGINE_MODEL` in the environment or `.env` only when needed; model overrides are restricted to the free-model list.

## Requirements

`pip install requests pyyaml` (Python 3.12). Git + gh for publishing; npm + wrangler for Workers deploys.
