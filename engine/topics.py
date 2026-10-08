"""Topic extraction + coverage clustering across competitors."""

import json
import re
from collections import Counter
from datetime import datetime, timezone

from engine import config, competitors, llm

STOPWORDS = set("""a an and are as at be by for from has have how in is it its of on or
that the this to was were what when where which who will with you your can
best free online tool tools using uses use get getting make making without
i we they them their our us my me do does did done should would could may
might must shall vs versus guide tutorial tips tricks top why not no new
""".split())


def _clean_title(text):
    """Strip HTML entities, site branding suffixes, and locale noise."""
    text = text.replace("&amp;", "and").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"[|\u2013\u2014-]+\s*(remove\.?bg|photoroom|pixelcut|cutout\.pro|img2go|pixian|freebg)[^.]*$", " ", text, flags=re.I)
    text = re.sub(r"\b(remove\.?bg|photoroom|pixelcut|cutout\.pro|img2go|pixian|freebg)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(blog|how to use it for|c\u00f3mo usarlo|comment l'utiliser|come usarlo|como usar|so verwenden|\u043a\u0430\u043a \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c)\b.*$", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(title_h1):
    text = _clean_title(title_h1)
    words = re.findall(r"[a-z][a-z0-9+-]{2,}", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def _topic_key(article):
    """LLM canonical topic key with lexical fallback."""
    text = article.get("title") or article.get("h1") or ""
    if not text:
        return ""
    cleaned = _clean_title(text)
    if not cleaned:
        return ""
    try:
        resp = llm.generate(
            "Normalize this blog article title into ONE canonical English blog topic as a "
            "short 3-7 word phrase. Lowercase, no branding, no domain names, no locale variants. "
            "Reply with ONLY the phrase.\n\n" + cleaned,
            max_tokens=40,
        )
        resp = resp.strip().strip('"').strip(".").lower()
        if 2 <= len(resp.split()) <= 9 and "\n" not in resp:
            return resp
    except Exception:
        pass
    words = _tokens(cleaned)
    return " ".join(words[:6]) if words else ""


def extract_topic_map(site):
    """Pull cached harvests, cluster into topics with coverage counts.
    Coverage = number of DISTINCT domains covering the topic (majority metric),
    LLM-normalized keys with a per-process cache to avoid re-asking.
    """
    key_cache = _load_key_cache(site["key"])
    site_dir = config.RESEARCH / site["key"]
    all_arts = []
    if site_dir.exists():
        for f in site_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for a in data.get("articles", []):
                    a["_domain"] = data.get("domain", f.stem)
                    all_arts.append(a)
            except Exception:
                continue
    cache_dirty = False
    topics = Counter()
    domains_by_topic = {}
    titles_by_topic = {}
    for a in all_arts:
        raw = a.get("title") or a.get("h1") or ""
        if not raw:
            continue
        ck = _cache_key(raw)
        if ck in key_cache:
            k = key_cache[ck]
        else:
            k = _topic_key(a)
            key_cache[ck] = k
            cache_dirty = True
        if not k:
            continue
        domains_by_topic.setdefault(k, set()).add(a["_domain"])
        titles_by_topic.setdefault(k, []).append(a["title"])
    if cache_dirty:
        _save_key_cache(site["key"], key_cache)
    for k, doms in domains_by_topic.items():
        topics[k] = len(doms)
    ranked = []
    for k in sorted(domains_by_topic, key=lambda x: -len(domains_by_topic[x])):
        ranked.append({
            "topic": k,
            "coverage": len(domains_by_topic[k]),
            "domains": sorted(domains_by_topic[k]),
            "sample_titles": titles_by_topic[k][:4],
        })
    return ranked


def _cache_key(title):
    return re.sub(r"\s+", " ", title.lower()).strip()[:120]


def _key_cache_path(site_key):
    return config.RESEARCH / f"{site_key}-topickeys.json"


def _load_key_cache(site_key):
    p = _key_cache_path(site_key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_key_cache(site_key, cache):
    _key_cache_path(site_key).write_text(
        json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8"
    )


def _new_from_top(articles_by_domain, seen_topics, top_domains):
    """Articles on top domains whose normalized topic is not in seen_topics."""
    fresh = {}
    for dom, arts in articles_by_domain.items():
        if dom not in top_domains:
            continue
        for a in arts:
            k = _topic_key(a)
            if not k or k in seen_topics:
                continue
            fresh.setdefault(k, a)
    return fresh


def build_topic_report(site):
    """Extract + cluster topics across all tracked competitors. Returns ranked report."""
    site_dir = config.RESEARCH / site["key"]
    per_domain = {}
    if site_dir.exists():
        for f in site_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                per_domain[data.get("domain", f.stem)] = data.get("articles", [])
            except Exception:
                continue
    topic_rows = extract_topic_map(site)
    return {
        "site": site["key"],
        "generated": now_iso(),
        "competitors": sorted(per_domain.keys()),
        "topics_by_coverage": topic_rows,
    }


def select_next_topics(site, report, max_n=None):
    """Pick topics to write next:
    1. evergreen: majority-covered topics not yet published on our site
    2. fresh: new topics from competitors (LLM-screened for blogworthiness)
    """
    max_n = max_n or config.MAX_ARTICLES_PER_RUN
    published = set()
    for slug, info in site.get("articles", {}).items():
        for w in _tokens(info.get("title", "")) + _tokens(slug.replace("-", " ")):
            published.add(w)
    candidates = []
    for t in report["topics_by_coverage"]:
        key_words = set(_tokens(t["topic"]))
        overlap_pub = len(key_words & published)
        already = overlap_pub >= max(1, len(key_words) // 2)
        candidates.append({**t, "already_covered": already})
    evergreen = [c for c in candidates if not c["already_covered"] and c["coverage"] >= 2]
    evergreen.sort(key=lambda x: (-x["coverage"], x["topic"]))
    fresh = [c for c in candidates if not c["already_covered"] and c["coverage"] == 1]
    # screen single-coverage fresh topics through the LLM: junk subjects get dropped
    fresh = [c for c in fresh if _screen_fresh(c["topic"], site)]
    fresh.sort(key=lambda x: -_fresh_score(x))
    picked = []
    for c in evergreen + fresh:
        if len(picked) >= max_n:
            break
        if not any(set(_tokens(c["topic"])) & set(_tokens(p["topic"])) for p in picked):
            picked.append(c)
    return {
        "evergreen_priority": evergreen[:5],
        "fresh_opportunities": fresh[:5],
        "picked_for_writing": picked[:max_n],
    }


def _fresh_score(topic_row):
    """Heuristic score: prefer topics with tool-intent words over brand/company topics."""
    t = topic_row["topic"]
    good = ("how", "remove", "convert", "create", "generate", "edit", "compress",
            "resize", "crop", "merge", "split", "background", "image", "photo",
            "png", "jpg", "pdf", "video", "audio", "mp3", "free", "online",
            "best", "guide", "tips", "compare", "vs", "alternative")
    bad = ("about", "mission", "vision", "story", "careers", "brand", "company",
           "press", "login", "signup", "pricing")
    score = sum(1 for w in good if w in t) - sum(2 for w in bad if w in t)
    if topic_row.get("sample_titles"):
        st = " ".join(topic_row["sample_titles"]).lower()
        score += sum(1 for w in ("how to", "what is", "tutorial", "guide", "vs", "tips") if w in st)
    return score


screen_cache = {}


def _screen_fresh(topic, site):
    """LLM gate: is this worth a blog article on OUR site? Cached per (site, topic)."""
    ck = (site["key"], topic)
    if ck in screen_cache:
        return screen_cache[ck]
    try:
        resp = llm.generate(
            f'You write SEO blog content for a small web tool site whose tool: "{site.get("description") or site["name"]}". '
            f'Is the blog topic "{topic}" a real, useful blog article subject for that site '
            '(something a human reader would search for and read, not a company/brand/about/announcement page)? '
            "Reply with only YES or NO.",
            max_tokens=10,
        )
        ok = resp.strip().upper().startswith("YES")
    except Exception:
        # fallback heuristic: reject obvious non-articles
        ok = not any(w in topic for w in ("about", "mission", "vision", "story", "careers", "brand"))
    screen_cache[ck] = ok
    return ok


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
