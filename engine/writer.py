"""SEO article writer: research-driven prompt -> markdown with YAML frontmatter."""

import json
import re

import yaml

from engine import config, llm, registry

WRITER_PROMPT = """You are an SEO content writer for the blog of a small free web-tool website.

Website: {name}
URL: {tool_url}
What the tool does: {description}
Primary keywords: {keywords}

You are writing ONE blog article about the topic: "{topic}"

Topics already published on our blog (do NOT duplicate, avoid heavy overlap):
{published}

Competitor research (articles real competitors published on this exact topic - match the
information needs they target, exceed them on completeness, do NOT copy):
{research}

Write the article in GitHub-flavored Markdown with YAML frontmatter. Requirements:
- frontmatter keys: title (<=60 chars, keyword-first), description (<=155 chars meta description),
  slug (lowercase-kebab), pubDate (YYYY-MM-DD), tags (3-5), keywords (3-5)
- 1200-1800 words, natural human tone, no fluff, never mention competitors by name
- H1 equals the title; then 5-8 H2 sections covering the search intent (what/how/steps/tips/
  mistakes/comparison/FAQ)
- one H2 "How to {tool_verb} step by step" with a numbered step list that references using {tool_url}
- one H2 FAQ with 4-5 questions as H3s (questions real users search for)
- mention the tool naturally 3-6 times with a link to {tool_url}
- no invented statistics, no fake quotes, no fabricated dates

Output ONLY the markdown file content starting with --- (frontmatter) and nothing else."""


def build_prompt(site, topic_row):
    researchdex = []
    for title in topic_row.get("sample_titles", []):
        researchdex.append(f"- {title}")
    published = [info["title"] for info in site.get("articles", {}).values()] or ["(none yet)"]
    return WRITER_PROMPT.format(
        name=site["name"],
        tool_url=site["tool_url"],
        description=site.get("description") or "a free online web tool",
        keywords=", ".join(site.get("keywords", [])),
        topic=topic_row["topic"],
        published="\n".join(f"- {t}" for t in published[:20]),
        research="\n".join(researchdex) or "(none - write from general knowledge of the search intent)",
        tool_verb=_tool_verb(site),
    )


def _tool_verb(site):
    kw = site.get("keywords") or []
    if kw:
        return kw[0]
    return f"use the {site['name']} tool"


def parse_article(md_text):
    """Extract frontmatter + body from LLM output; tolerate missing frontmatter."""
    md_text = md_text.strip()
    if md_text.startswith("```"):
        md_text = re.sub(r"^```[a-z]*\n", "", md_text)
        md_text = re.sub(r"\n```$", "", md_text).strip()
    fm = {}
    body = md_text
    if md_text.startswith("---"):
        parts = re.split(r"^---\s*$", md_text, maxsplit=2, flags=re.M)
        if len(parts) >= 3:
            fm_text, body = parts[1].strip(), parts[2].strip()
            for line in fm_text.splitlines():
                m = re.match(r"^([A-Za-z_-]+)\s*:\s*(.*)$", line)
                if not m:
                    continue
                key, val = m.group(1).strip(), m.group(2).strip()
                if val.startswith("[") and val.endswith("]"):
                    val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                else:
                    val = val.strip("'\"")
                fm[key.lower()] = val
    return fm, body


def sanity_check(fm, body, topic):
    """Cheap acceptance gate: reject junk output before it hits the blog."""
    words = len(re.findall(r"\S+", body))
    problems = []
    h2s = re.findall(r"^##\s+", body, flags=re.M)
    if words < 500:
        problems.append(f"too short ({words} words)")
    if len(h2s) < 3:
        problems.append(f"too few H2 sections ({len(h2s)})")
    if "```" in body:
        problems.append("contains code fences")
    title = fm.get("title", "")
    if not title:
        problems.append("no title in frontmatter")
    return problems


def write_article(site, topic_row):
    """Generate one article for one topic. Returns (slug, relpath, md_text) or raises."""
    prompt = build_prompt(site, topic_row)
    md_text = llm.generate(prompt, max_tokens=8192)
    fm, body = parse_article(md_text)
    problems = sanity_check(fm, body, topic_row["topic"])
    if problems:
        # one retry with corrective feedback
        md_text = llm.generate(
            prompt + "\n\nYour previous attempt had problems: " + "; ".join(problems) +
            ". Regenerate the FULL article fixing these problems.",
            max_tokens=8192,
        )
        fm, body = parse_article(md_text)
        problems = sanity_check(fm, body, topic_row["topic"])
        if problems:
            raise ValueError("article rejected: " + "; ".join(problems))
    title = fm.get("title") or topic_row["topic"].title()
    slug = registry.slugify(fm.get("slug") or title)
    from datetime import datetime, timezone
    date = fm.get("pubDate") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    keywords = fm.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [t.strip() for t in keywords.split(",") if t.strip()]
    final_fm = {
        "title": title,
        "description": fm.get("description", ""),
        "slug": slug,
        "pubDate": date,
        "tags": tags,
        "keywords": keywords,
        "engine": "seo-blog-engine",
        "topicSource": topic_row.get("domains", []),
    }
    import yaml
    fm_str = yaml.safe_dump(final_fm, sort_keys=False, allow_unicode=True)
    md = f"---\n{fm_str}---\n\n{body}\n"
    return slug, title, md

