"""Site registry: the list of tool websites the engine writes SEO content for."""

import json
import re
from datetime import datetime, timezone

from engine import config


def load_sites():
    if config.SITES.exists():
        return json.loads(config.SITES.read_text(encoding="utf-8"))
    return []


def save_sites(sites):
    config.SITES.write_text(
        json.dumps(sites, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80] or "untitled"


def add_site(key, name, tool_url, repo, output_dir, description="",
             keywords=None, competitors=None):
    """Register (or update) a site. output_dir = path to the site's blog content dir."""
    sites = load_sites()
    entry = None
    for s in sites:
        if s["key"] == key:
            entry = s
            break
    if entry is None:
        entry = {"key": key, "created": now_iso(), "competitors": [], "articles": {}}
        sites.append(entry)
    entry.update({
        "name": name,
        "tool_url": tool_url,
        "repo": repo,
        "output_dir": str(output_dir),
        "description": description,
        "keywords": keywords or [],
        "competitors": competitors or entry.get("competitors", []),
    })
    save_sites(sites)
    return entry


def get_site(key):
    for s in load_sites():
        if s["key"] == key:
            return s
    raise KeyError(f"site '{key}' not registered in {config.SITES}")


def register_article(site_key, slug, title, source):
    """Record that an article was published; source = topic provenance."""
    sites = load_sites()
    for s in sites:
        if s["key"] == site_key:
            s.setdefault("articles", {})[slug] = {
                "title": title,
                "source": source,
                "published": now_iso(),
            }
            break
    save_sites(sites)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
