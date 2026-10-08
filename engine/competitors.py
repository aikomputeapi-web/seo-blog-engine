"""Competitor discovery + blog-topic harvesting (sitemaps, blog pages, HTML)."""

import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urljoin, urlparse
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
        # If the index has no article sitemap, let the blog-page fallback probe
        # common paths instead of treating every product/format page as a post.
        for child in blog_children[:5]:
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
HARVEST_VERSION = 6  # bump when crawl filters or request behavior changes

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
        parsed = urlparse(u)
        path = parsed.path.lower()
        host = parsed.netloc.lower().removeprefix("www.")
        if host != base_domain.removeprefix("www."):
            continue
        blog_host_article = host.startswith("blog.") and bool(path.strip("/"))
        article_path = any(h in path for h in BLOG_HINTS)
        if (article_path or blog_host_article) and not path.endswith((".pdf", ".jpg", ".png", ".xml")):
            out.append(u)
    return out[: config.MAX_SITEMAP_URLS]


def _is_index_page(url, title=""):
    path = urlparse(url).path.lower().strip("/")
    if not path or path in ("blog", "resources", "guides", "articles", "news"):
        return True
    parts = path.split("/")
    if any(part in {"category", "categories", "tag", "tags", "page", "author", "feed",
                    "comments", "wp-json", "wp-content", "wp-admin", "wp-includes"}
           for part in parts):
        return True
    if path.endswith((".php", ".xml", ".css", ".js", ".json", ".pdf", ".jpg", ".jpeg",
                      ".png", ".gif", ".svg", ".webp", ".woff", ".woff2", ".ico")):
        return True
    cleaned = (title or "").lower().strip()
    return cleaned in ("blog", "news", "resources", "articles")


CONVERSION_RELEVANCE = re.compile(
    r"\b(convert\w*|conversion|converter|format\w*|file[- ]type|file[- ]extension|extension|codec|container|compress\w*|archive|"
    r"pdf|docx|pptx|xlsx|xls|csv|epub|mp3|mp4|wav|aac|flac|ogg|png|jpe?g|heic|heif|avif|webp|svg|zip|7z|dmg|3g2|3gp|lrf|lha|raw)\b",
    re.I,
)


def _is_conversion_related(meta):
    raw_title = meta.get("title", "").lower()
    # CloudConvert's MCP integration is a directly relevant converter workflow,
    # even when the article's metadata does not repeat the word "conversion".
    if "cloudconvert" in raw_title and "mcp" in raw_title:
        return True
    text = " ".join([
        _clean_source_title(meta.get("title", "")), meta.get("description", ""), meta.get("h1", ""),
        " ".join(meta.get("h2s", [])),
    ])
    text = re.sub(r"\b(?:cloudconvert|freeconvert|zamzar|online[- ]convert|convert\.online)\b", " ", text, flags=re.I)
    return bool(CONVERSION_RELEVANCE.search(text))


def _clean_source_title(title):
    """Remove recurring publisher suffixes before matching and topic clustering."""
    title = unescape(title).replace("\ufffd", "|")
    for pattern in (
        r"\s*[|–—-]\s*online file conversion blog\b.*$",
        r"\s*[|–—-]\s*cloudconvert blog\b.*$",
        r"\s*[|–—-]\s*freeconvert blog\b.*$",
        r"\s*[|–—-]\s*blog\b.*$",
        r"\s*[|–—-]\s*convert\.online\b.*$",
        r"\s*[|–—-]\s*zamzar\b.*$",
    ):
        title = re.sub(pattern, "", title, flags=re.I).strip()
    return title


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
    h1 = unescape(re.sub(r"<[^>]+>", "", h1))
    h2s = [unescape(re.sub(r"<[^>]+>", "", h)) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)][:8]
    return {
        "url": url,
        "title": re.sub(r"\s+", " ", _clean_source_title(re.sub(r"<[^>]+>", "", title)))[:160],
        "description": unescape(desc)[:300],
        "h1": h1[:160],
        "h2s": [re.sub(r"\s+", " ", h).strip()[:120] for h in h2s if h.strip()],
        "scraped": now_iso(),
    }


def _scrape_relevant_articles(urls):
    """Fetch a bounded set of candidate pages concurrently and keep relevant posts."""
    unique = list(dict.fromkeys(urls))[: config.MAX_ARTICLES_PER_SCRAPE]
    if not unique:
        return []
    found = []
    workers = min(config.CRAWL_ARTICLE_WORKERS, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scrape_article_meta, url): url for url in unique}
        for future in as_completed(futures):
            try:
                meta = future.result()
            except Exception:
                continue
            url = futures[future]
            if (meta and meta["title"] and not _is_non_article(url, meta["title"])
                    and not _is_index_page(url, meta["title"])
                    and _is_conversion_related(meta)):
                found.append(meta)
    return found


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def harvest_competitor(site_key, domain, sample_url=None):
    """Harvest relevant articles from a sitemap or the configured blog page."""
    cache = config.RESEARCH / site_key
    cache.mkdir(parents=True, exist_ok=True)
    cache_file = cache / f"{domain}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if (data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d")
                and data.get("harvest_version") == HARVEST_VERSION):
            return data
    sitemap_urls = [u for u in filter_article_urls(get_sitemap_urls(domain), domain)
                    if not _is_non_article(u)]
    arts = _scrape_relevant_articles(sitemap_urls)
    # Sitemap-less fallback: use the configured blog landing page, then common paths.
    if not arts:
        probes = [sample_url] if sample_url else []
        probes.extend(f"https://{domain}{p}" for p in ("/", "/blog/"))
        seen_probes = set()
        for page_url in probes:
            if not page_url or page_url in seen_probes:
                continue
            seen_probes.add(page_url)
            try:
                r = _get(page_url)
                if r.status_code == 200:
                    links = re.findall(r"href=[\"']([^\"'#?]+)", r.text, re.I)
                    candidates = []
                    seen = set()
                    for href in links:
                        article_url = urljoin(page_url, unescape(href))
                        parsed = urlparse(article_url)
                        host = parsed.netloc.lower().removeprefix("www.")
                        if host != domain.lower().removeprefix("www."):
                            continue
                        path = parsed.path.lower()
                        blog_host = host.startswith("blog.")
                        if not (blog_host or any(h in path for h in BLOG_HINTS)):
                            continue
                        if article_url in seen or _is_index_page(article_url):
                            continue
                        seen.add(article_url)
                        candidates.append(article_url)
                        if len(candidates) >= config.MAX_ARTICLES_PER_SCRAPE:
                            break
                    arts = _scrape_relevant_articles(candidates)
                    if arts:
                        break
            except Exception:
                continue
    data = {"domain": domain, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "harvest_version": HARVEST_VERSION,
            "articles": arts}
    cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
