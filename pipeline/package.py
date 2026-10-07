"""Builds the public bundle: the only part of the project that is ever published.
Usage: python -m pipeline.package [--out dist/public] [--indexable]

Public: the dashboard (HTML, CSS, JavaScript) and its exported JSON (mart summaries, per-item stock histories, the scorecard). Nothing else is copied: no raw or source files,
no warehouse, no answer key, no code. The bundle is a plain folder of static files that any static host can serve (Cloudflare Pages, S3, a web server).
The build is deterministic (no timestamps in the manifest), and writes cache and security headers, a robots.txt that asks search engines to stay away until launch
(pass --indexable at launch), and manifest.json listing every file with its size and checksum."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from . import config as cfg

DASH = cfg.ROOT / "dashboard"
ALLOWED = {".html", ".css", ".js", ".json"}
HEADERS = """/data/*
  Cache-Control: no-cache
/js/*
  Cache-Control: public, max-age=300
/css/*
  Cache-Control: public, max-age=300
/config.json
  Cache-Control: no-cache
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
"""


def build(out: Path, indexable: bool = False) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    n = 0
    for p in sorted(DASH.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix not in ALLOWED:
            raise SystemExit(f"refusing to publish {p.relative_to(DASH)}: only {sorted(ALLOWED)} files go in the public bundle")
        dst = out / p.relative_to(DASH)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    (out / "_headers").write_text(HEADERS, encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n" if indexable else "User-agent: *\nDisallow: /\n", encoding="utf-8")
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file():
            files[p.relative_to(out).as_posix()] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
    summary = {"files": len(files), "bytes": sum(v["bytes"] for v in files.values()), "indexable": indexable,
               "fingerprint": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps({**summary, "entries": files}, indent=0, sort_keys=True), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(cfg.ROOT / "dist" / "public"))
    ap.add_argument("--indexable", action="store_true", help="let search engines index the site (use at launch)")
    a = ap.parse_args()
    s = build(Path(a.out), a.indexable)
    print(f"packaged {s['files']:,} files, {s['bytes'] / 1e6:.1f} MB, fingerprint {s['fingerprint']} -> {a.out}")


if __name__ == "__main__":
    main()
