# seo-blog-engine

Autonomous, competitor-following SEO blog writer for a fleet of small single-tool websites.

Each registered tool website gets continuous blog content modeled on what its competitors publish: the engine harvests competitor blog sitemaps, normalizes and clusters topics by how many competitors cover them, screens new topics with an LLM, writes SEO-structured articles, and publishes them straight into each site's repo (commit + push, or wrangler deploy). Runs daily on its own.

## How it works

1. **Registry** (`data/sites.json`) - every tool site: name, tool URL, repo, blog content dir, keywords, tracked competitors, and a log of published articles.
2. **Research** (`engine/competitors.py`) - pulls each competitor's `sitemap.xml` (robots.txt fallback + blog-path probing), scrapes `<title>`/meta description/H2s per article, cached per day in `data/research/<site>/`.
3. **Topics** (`engine/topics.py`) - LLM-normalizes article titles into canonical topics, clusters them by distinct-domain coverage. Evergreen topics (covered by 2+ competitors) get priority; single-coverage fresh topics are LLM-screened so company/about/brand pages never become articles.
4. **Writer** (`engine/writer.py`) - builds a research-driven prompt (competitor samples, already-published guard, keyword-first title/meta/H2/FAQ structure), generates markdown, sanity-gates it (word count, H2 count, no fences), retries once with corrective feedback.
5. **Publisher** (`engine/publisher.py`) - writes the article into the site repo, commits, pushes.
6. **Autonomy** (`daily-run.ps1` + Startup `seo-blog-engine-daily.vbs`) - once per day: full cycle for every registered site, then `wrangler deploy` for any site with a `wrangler.jsonc`. Logs to `logs/scheduled-YYYY-MM-DD.log` with a once-per-day state guard.

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

## LLM

Uses the zen router (`https://zen.nowrouter.store/v1`, OpenAI-compatible, free, no key) with `gemini-2.5-flash` by default. Override with `BLOGENGINE_LLM_URL` / `BLOGENGINE_MODEL` (env or `.env`). The Gemini direct API key noted in this workspace's AGENTS.md is invalid (HTTP 400) - do not reuse it.

## Requirements

`pip install requests pyyaml` (Python 3.12). Git + gh for publishing; npm + wrangler for Workers deploys.
