"""Competitor discovery + blog-topic harvesting (sitemaps, blog pages, HTML)."""

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from datetime import datetime, timezone

import requests

from engine import config


def _get(url):
    return requests.get(
        url,
        timeout=config.HTTP_TIMEOUT,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def discover_competitors(keywords, exclude_domains=(), max_n=None):
    """Web-search for rival tool sites using the websearch-backed DDG HTML endpoint."""
    max_n = max_n or config.MAX_COMPETITORS
    found = {}
    for kw in keywords:
        try:
            r = _get(f"https://html.duckduckgo.com/html/?q={kw.replace(' ', '+')}")
            for m in re.finditer(r'uddg=([^&"]+)', r.text):
                from urllib.parse import unquote
                url = unquote(m.group(1))
                if url.startswith("http"):
                    found[url] = True
        except Exception:
            pass
    ranked = []
    for url in found:
        dom = urlparse(url).netloc.lower()
        dom = dom[4:] if dom.startswith("www.") else dom
        if (not dom or
                any(x in dom for x in ("duckduckgo", "google", "youtube",
                                       "reddit", "wikipedia", "facebook",
                                       "twitter", "x.com", "linkedin",
                                       "pinterest", "amazon")) or
                dom in exclude_domains):
            continue
        scored = 0
        for kw in keywords:
            for part in kw.lower().split():
                if part in dom or part in url.lower():
                    scored += 1
        from urllib.parse import unquote_plus
        ranked.append({"domain": dom, "url": url, "score": scored})
    ranked.sort(key=lambda x: -x["score"])
    out, seen = [], set()
    for r in ranked:
        if r["domain"] not in seen:
            seen.add(r["domain"])
            out.append({"domain": r["domain"], "sample_url": r["url"]})
        if len(out) >= max_n:
            break
    return out


def get_sitemap_urls(domain):
    """Find sitemap.xml (or robots.txt pointer) and return article-ish URLs."""
    urls, xml_text = [], None
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"):
        try:
            r = _get(f"https://{domain}{path}")
            if r.status_code == 200 and ("xml" in r.headers.get("Content-Type", "") or r.text.lstrip().startswith("<")):
                xml_text = r.text
                break
        except Exception:
            continue
    if xml_text is None:
        try:
            r = _get(f"https://{domain}/robots.txt")
            if r.status_code == 200:
                m = re.search(r"Sitemap:\s*(\S+)", r.text)
                if m:
                    r2 = _get(m.group(1))
                    if r2.status_code == 200:
                        xml_text = r2.text
        except Exception:
            pass
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    # sitemap index -> child sitemaps (prefer blog/post ones)
    child_locs = [e.text for e in root.findall("sm:sitemap/sm:loc", ns)]
    if child_locs:
        blog_children = [c for c in child_locs if any(w in c.lower() for w in ("blog", "post", "article", "guide"))]
        for child in (blog_children or child_locs)[:5]:
            try:
                r = _get(child)
                if r.status_code == 200:
                    urls.extend(_extract_locs(r.text, ns))
            except Exception:
                continue
    else:
        urls = _extract_locs(xml_text, ns)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[: config.MAX_SITEMAP_URLS]


def _extract_locs(xml_text, ns):
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
        return [e.text for e in root.findall("sm:url/sm:loc", ns) if e.text]
    except Exception:
        return []


BLOG_HINTS = ("blog", "guide", "tips", "how-to", "article", "post", "news", "resources", "help")

NON_ARTICLE = ("about", "careers", "pricing", "contact", "login", "signup", "sign-up",
               "terms", "privacy", "legal", "press", "jobs", "team", "company",
               "account", "apps", "download", "pricing", "refund", "imprint",
               "help-center", "helpcenter", "faq", "über", "à-propos")


def _is_non_article(url, title=""):
    low = url.lower()
    if any(p in low for p in NON_ARTICLE):
        # "about" inside a real article slug is rare; blog paths give false positives rarely
        t = (title or "").lower()
        return any(p in t[:40] for p in ("about ", "mission", "careers", "pricing", "contact"))
    return False


def filter_article_urls(urls, base_domain):
    out = []
    for u in urls:
        low = u.lower()
        if urlparse(u).netloc.lower().removeprefix("www.") != base_domain:
            continue
        if any(h in low for h in BLOG_HINTS) and not low.endswith((".pdf", ".jpg", ".png", ".xml")):
            out.append(u)
    if not out:  # fallback: everything not the homepage
        out = [u for u in urls if u.rstrip("/") != f"https://{base_domain}" and u.rstrip("/") != f"https://www.{base_domain}"]
    return out[: config.MAX_SITEMAP_URLS]


def scrape_article_meta(url):
    """Pull one page's <title>, meta description, H1/H2s without a heavy parse."""
    try:
        r = _get(url)
        if r.status_code != 200 or len(r.text) > 2_000_000:
            return None
        html = r.text
    except Exception:
        return None

    def first(pattern, flags=re.I | re.S):
        m = re.search(pattern, html, flags)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    title = first(r"<title[^>]*>(.*?)</title>")
    desc = first(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']') or \
           first(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']')
    h1 = first(r"<h1[^>]*>(.*?)</h1>")
    h1 = re.sub(r"<[^>]+>", "", h1)
    h2s = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)][:8]
    return {
        "url": url,
        "title": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title))[:160],
        "description": desc[:300],
        "h1": h1[:160],
        "h2s": [re.sub(r"\s+", " ", h).strip()[:120] for h in h2s if h.strip()],
        "scraped": now_iso(),
    }


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def harvest_competitor(site_key, domain):
    """Full harvest for one competitor: sitemap -> article URLs -> meta. Cached per day."""
    cache = config.RESEARCH / site_key
    cache.mkdir(parents=True, exist_ok=True)
    cache_file = cache / f"{domain}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            return data
    sitemap_urls = [u for u in filter_article_urls(get_sitemap_urls(domain), domain)
                    if not _is_non_article(u)]
    arts = []
    for u in sitemap_urls[: config.MAX_ARTICLES_PER_SCRAPE]:
        meta = scrape_article_meta(u)
        if meta and meta["title"] and not _is_non_article(u, meta["title"]):
            arts.append(meta)
    # sitemap-less fallback: probe common blog paths
    if not arts:
        for p in ("/blog", "/blog/", "/resources", "/guides", "/articles"):
            try:
                r = _get(f"https://{domain}{p}")
                if r.status_code == 200:
                    links = re.findall(r'href="(/[^"#?]+)"', r.text)
                    seen = set()
                    for l in links:
                        if any(h in l.lower() for h in BLOG_HINTS) and l not in seen:
                            seen.add(l)
                            meta = scrape_article_meta(f"https://{domain}{l}")
                            if meta and meta["title"]:
                                arts.append(meta)
                            if len(arts) >= config.MAX_ARTICLES_PER_SCRAPE:
                                break
                    if arts:
                        break
            except Exception:
                continue
    data = {"domain": domain, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "articles": arts}
    cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
