"""seo-blog-engine CLI.

Usage:
  python -m engine.cli run [--site KEY] [--max N] [--no-push]
  python -m engine.cli research [--site KEY] [--discover]   # harvest competitor blogs
  python -m engine.cli report [--site KEY]                  # topic report to stdout
  python -m engine.cli addsite ...                          # register a site
  python -m engine.cli loop                                 # continuous daemon
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from engine import competitors, config, publisher, registry, topics, writer


def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)


def _ensure_ours_excluded(site):
    dom = site.get("tool_url", "").replace("https://", "").replace("http://", "").split("/")[0]
    return dom[4:] if dom.startswith("www.") else dom


def cmd_research(args):
    sites = [registry.get_site(args.site)] if args.site else registry.load_sites()
    for site in sites:
        key = site["key"]
        ours = _ensure_ours_excluded(site)
        comp_list = site.get("competitors", [])
        if args.discover or not comp_list:
            log(f"{key}: discovering competitors...")
            found = competitors.discover_competitors(site.get("keywords", []), exclude_domains={ours})
            # keep known ones, add new
            known = {c["domain"] for c in comp_list}
            for c in found:
                if c["domain"] not in known:
                    comp_list.append(c)
            site["competitors"] = comp_list[: config.MAX_COMPETITORS]
            registry.save_sites(registry.load_sites())
            log(f"{key}: tracking {len(comp_list)} competitors: " +
                ", ".join(c["domain"] for c in comp_list))
        results = {}
        for c in site.get("competitors", []):
            dom = c["domain"] if isinstance(c, dict) else c
            log(f"{key}: harvesting {dom} ...")
            try:
                data = competitors.harvest_competitor(key, dom)
                results[dom] = len(data.get("articles", []))
                log(f"{key}: {dom} -> {results[dom]} articles")
            except Exception as e:
                log(f"{key}: {dom} FAILED: {e}")
                results[dom] = 0
        # write a research snapshot
        snap = {
            "site": key,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "competitors": results,
        }
        snap_file = config.RESEARCH / f"{key}-latest-research.json"
        snap_file.write_text(json.dumps(snap, indent=2), encoding="utf-8")


def cmd_report(args):
    sites = [registry.get_site(args.site)] if args.site else registry.load_sites()
    for site in sites:
        report = topics.build_topic_report(site)
        out = config.RESEARCH / f"{site['key']}-topic-report.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        sel = topics.select_next_topics(site, report)
        log(f"== {site['key']}: {len(report['topics_by_coverage'])} topics, "
            f"{sum(1 for t in report['topics_by_coverage'] if t['coverage'] > 1)} covered by 2+ competitors")
        for t in report["topics_by_coverage"][:10]:
            log(f"   {t['coverage']}x  {t['topic']}")
        log(f"   evergreen priority: {[t['topic'] for t in sel['evergreen_priority'][:3]]}")
        log(f"   fresh: {[t['topic'] for t in sel['fresh_opportunities'][:3]]}")
        log(f"   picked to write: {[t['topic'] for t in sel['picked_for_writing']]}")


def cmd_run(args):
    sites = [registry.get_site(args.site)] if args.site else registry.load_sites()
    all_results = []
    for site in sites:
        key = site["key"]
        log(f"===== {key} =====")
        # 1. research (competitors must exist; discover on first run only)
        if not site.get("competitors"):
            cmd_research(argparse.Namespace(site=key, discover=False))
            site = registry.get_site(key)
        else:
            cmd_research(argparse.Namespace(site=key, discover=False))
            site = registry.get_site(key)
        # 2. topic report + selection
        report = topics.build_topic_report(site)
        sel = topics.select_next_topics(site, report)
        picked = sel["picked_for_writing"][: args.max]
        if not picked:
            log(f"{key}: nothing new to write (all top topics covered)")
            continue
        # 3. write + publish
        out_dir = Path(site["output_dir"])
        if not out_dir.is_absolute():
            out_dir = Path(site["repo"]) / out_dir  # relative output_dir is repo-relative
        if not out_dir.exists():
            log(f"{key}: output dir missing ({out_dir}) - creating")
            out_dir.mkdir(parents=True, exist_ok=True)
        for t in picked:
            log(f"{key}: writing article on '{t['topic']}' "
                f"(coverage {t['coverage']}, domains {t['domains']})")
            try:
                slug, title, md = writer.write_article(site, t)
                res = {"site": key, "slug": slug, "title": title}
                if args.no_push:
                    p = out_dir / f"{slug}.md"
                    p.write_text(md, encoding="utf-8")
                    res.update({"written": str(p), "committed": False})
                    log(f"{key}: wrote (no push) {p}")
                else:
                    pub = publisher.publish_article(
                        site["repo"], str(Path(site["output_dir"])), slug, md,
                        message=f"blog: {title[:120]}",
                    )
                    res.update(pub)
                    log(f"{key}: published {slug} (committed={pub['committed']}, pushed={pub.get('pushed')})")
                registry.register_article(key, slug, title,
                                          source={"topic": t["topic"], "domains": t["domains"], "coverage": t["coverage"]})
                all_results.append(res)
            except Exception as e:
                log(f"{key}: FAILED '{t['topic']}': {e}")
    results_file = config.STATE / "last-run.json"
    results_file.write_text(json.dumps({
        "finished": now_iso(), "results": all_results}, indent=2), encoding="utf-8")
    log(f"run complete: {len(all_results)} articles")


def cmd_addsite(args):
    entry = registry.add_site(
        key=args.key, name=args.name, tool_url=args.tool_url, repo=args.repo,
        output_dir=args.output_dir, description=args.description or "",
        keywords=[k.strip() for k in (args.keywords or "").split(",") if k.strip()],
    )
    log(f"registered site: {entry['key']} -> {entry['output_dir']}")


def cmd_loop(args):
    log(f"continuous loop started (every {args.every_hours}h, Ctrl+C to stop)")
    while True:
        try:
            cmd_run(argparse.Namespace(site=None, max=config.MAX_ARTICLES_PER_RUN, no_push=False))
        except Exception as e:
            log(f"loop iteration failed: {e}")
        time.sleep(args.every_hours * 3600)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(prog="seo-blog-engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="research + write + publish new articles")
    p.add_argument("--site", default=None)
    p.add_argument("--max", type=int, default=config.MAX_ARTICLES_PER_RUN)
    p.add_argument("--no-push", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("research", help="discover/harvest competitor blogs")
    p.add_argument("--site", default=None)
    p.add_argument("--discover", action="store_true", help="re-discover competitors too")
    p.set_defaults(func=cmd_research)

    p = sub.add_parser("report", help="topic coverage report")
    p.add_argument("--site", default=None)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("addsite", help="register a tool website")
    p.add_argument("--key", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--url", dest="tool_url", required=True)
    p.add_argument("--repo", required=True, help="git repo path of the site")
    p.add_argument("--dir", dest="output_dir", required=True, help="blog content dir inside repo")
    p.add_argument("--description", default="")
    p.add_argument("--keywords", default="")
    p.set_defaults(func=cmd_addsite)

    p = sub.add_parser("loop", help="continuous daemon")
    p.add_argument("--every-hours", type=float, default=24)
    p.set_defaults(func=cmd_loop)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
