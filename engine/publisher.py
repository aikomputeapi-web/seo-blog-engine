"""Publisher: write articles into a site repo and push (auto-deploy via host)."""

import subprocess
from pathlib import Path

from engine import config, registry


def _run(cmd, cwd, check=True):
    r = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, shell=True
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {r.stderr.strip() or r.stdout.strip()[:400]}")
    return r


def publish_article(site_repo, rel_dir, slug, md_text, message=None):
    """Write the md file into the site repo, commit, push. Returns commit status."""
    repo = Path(site_repo)
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a git repo: {repo}")
    blog_dir = repo / rel_dir
    blog_dir.mkdir(parents=True, exist_ok=True)
    out_file = blog_dir / f"{slug}.md"
    out_file.write_text(md_text, encoding="utf-8")
    _run("git add -A", repo)
    status = _run("git status --porcelain", repo)
    changed = bool(status.stdout.strip())
    if not changed:
        return {"written": str(out_file), "committed": False, "note": "no changes"}
    _run(f'git commit -m "{(message or ("blog: " + slug))[:200]}"', repo)
    push = _run("git push", repo, check=False)
    return {
        "written": str(out_file),
        "committed": True,
        "pushed": push.returncode == 0,
        "push_note": (push.stderr or push.stdout).strip()[:300] if push.returncode else "",
    }
