"""Phase 9 gate: is the project ready to be published, without publishing anything?
Usage: python -m generator.validate_package

A. The public bundle: built from scratch it is deterministic, holds only allowed file types, contains nothing private (answer-key names, local paths, personal addresses,
   keys), every reference resolves, and it serves correctly from a plain static web server.
B. The repository: what a first commit would contain is small and free of generated data and the answer key; the code imports cleanly from a clean copy; dependencies are pinned
   and complete; the data dictionary matches the warehouse; documents exist and their links work.
Writes docs/PHASE9_REPORT.md. Nothing is uploaded, pushed or configured."""
from __future__ import annotations

import ast
import hashlib
import http.server
import json
import os
import random
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

import duckdb

from . import config as G
from .validate import Results

ROOT = G.ROOT
DIST = ROOT / "dist" / "public"
DOCS = ROOT / "docs"


class R7(Results):
    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok), "GATE"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    def info(self, group, name, measured):
        self.rows.append((group, name, measured, "reported", True, "INFO"))
        print(f"  [INFO] {name}: {measured}")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows if r[5] == "GATE")


PRIVATE = [r"truth_[a-z_]+", r"state_end_of_history", r"[A-Za-z]:\\\\?Users", r"/Users/", r"\.duckdb", r"sources_live", r"[\w.+-]+@[\w-]+\.[a-z]{2,}", r"(?i)kwarteng|tiffany|oseia",
           r"AKIA[0-9A-Z]{12,}", r"ghp_[A-Za-z0-9]{20,}", r"sk-[A-Za-z0-9]{20,}", r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{6,}"]


def text_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in {".html", ".css", ".js", ".json", ".txt", ".md", ".py", ".sql", ".yml", ".csv", ".toml", ""} and p.stat().st_size < 3_000_000:
            yield p


# ----------------------------------------------------------------------------------------------------------------------------- A
def bundle(R):
    print("A. The public bundle")
    from pipeline import package
    s1 = package.build(DIST)
    s2 = package.build(DIST)
    R.add("A", "building the bundle twice gives the identical bundle", f"{s1['files']:,} files, {s1['bytes'] / 1e6:.1f} MB; fingerprints {s1['fingerprint']} and {s2['fingerprint']}", "identical", s1["fingerprint"] == s2["fingerprint"])
    exts = {}
    for p in DIST.rglob("*"):
        if p.is_file():
            exts[p.suffix or p.name] = exts.get(p.suffix or p.name, 0) + 1
    ok_ext = set(exts) <= {".html", ".css", ".js", ".json", ".txt", "_headers"}
    big = max((p.stat().st_size for p in DIST.rglob("*") if p.is_file()))
    R.add("A", "only web file types are published, and the bundle is far inside static-host limits", f"types {dict(sorted(exts.items()))}; largest file {big / 1e6:.2f} MB; {s1['files']:,} files", "web types only; < 20,000 files; no file over 5 MB", ok_ext and s1["files"] < 20000 and big < 5_000_000)
    hits = {}
    for p in text_files(DIST):
        t = p.read_text(encoding="utf-8", errors="ignore")
        for pat in PRIVATE:
            m = re.search(pat, t)
            if m:
                hits.setdefault(pat, []).append(f"{p.relative_to(DIST).as_posix()}: {m.group(0)[:40]}")
    R.add("A", "nothing private is in the bundle: no answer-key names, local paths, database names, addresses or keys", f"{sum(len(v) for v in hits.values())} matches over {len(list(text_files(DIST))):,} text files" + ("" if not hits else " -> " + "; ".join(f"{k}: {v[:2]}" for k, v in hits.items())), "0", not hits)
    # references resolve
    js = list((DIST / "js").rglob("*.js"))
    miss = []
    for p in js:
        t = p.read_text(encoding="utf-8")
        for rel in re.findall(r"from\s+'(\.[^']+)'", t) + re.findall(r"import\('(\.[^']+)'\)", t):
            if not (p.parent / rel).resolve().exists():
                miss.append(f"{p.name} -> {rel}")
        for name in re.findall(r"get(?:JSON|Optional)\('([a-z_]+\.json)'\)", t):
            if not (DIST / "data" / name).exists() and name != "live.json":
                miss.append(f"{p.name} -> data/{name}")
    html = (DIST / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:href|src)="((?!data:|http|#)[^"]+)"', html):
        if not (DIST / ref).exists():
            miss.append(f"index.html -> {ref}")
    nsku = json.loads((DIST / "data" / "overview.json").read_text())["skus"]
    shards = len(list((DIST / "data" / "sku").glob("*.json")))
    for m_ in ("main", "nav", "more", "sheetbg", "sheet", "theme", "asof", "live"):
        if f'id="{m_}"' not in html:
            miss.append(f"index.html lacks #{m_}")
    R.add("A", "every file the pages refer to exists, including one history file per item", f"{len(js)} scripts; {len(miss)} broken references; {shards:,} item histories for {nsku:,} items", "none broken, one per item", not miss and shards == nsku)
    # serve it
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(DIST), **k)

    class Q(socketserver.TCPServer):
        allow_reuse_address = True
    srv = Q(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    bad = []
    try:
        random.seed(9)
        urls = ["/", "/config.json", "/robots.txt", "/_headers", "/manifest.json"] + [f"/js/{p.relative_to(DIST / 'js').as_posix()}" for p in js] + ["/css/style.css"] + [f"/data/{p.name}" for p in (DIST / "data").glob("*.json")]
        urls += [f"/data/sku/{p.name}" for p in random.sample(list((DIST / "data" / "sku").glob("*.json")), 25)]
        for u in urls:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{u}", timeout=20) as r:
                    body = r.read()
                    if r.status != 200:
                        bad.append(f"{u} {r.status}")
                    elif u.endswith(".json"):
                        json.loads(body)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{u} {type(e).__name__}")
    finally:
        srv.shutdown()
    R.add("A", "the bundle serves from a plain static web server: every page, script and data file answers and every JSON file parses", f"{len(urls)} requests, {len(bad)} failures" + ("" if not bad else ": " + ", ".join(bad[:4])), "0 failures", not bad)
    robots = (DIST / "robots.txt").read_text()
    tmp = Path(tempfile.mkdtemp())
    package.build(tmp / "x", indexable=True)
    open_robots = (tmp / "x" / "robots.txt").read_text()
    shutil.rmtree(tmp, ignore_errors=True)
    hd = (DIST / "_headers").read_text()
    R.add("A", "search engines are kept out until launch, and data is never cached stale", f"default robots: {robots.splitlines()[1]}; --indexable: {open_robots.splitlines()[1]}; data cache rule present: {'no-cache' in hd.split('/js/*')[0]}",
          "Disallow by default, Allow with the flag, no-cache on data", robots.splitlines()[1] == "Disallow: /" and open_robots.splitlines()[1] == "Allow: /" and "no-cache" in hd.split("/js/*")[0])
    cfgj = json.loads((DIST / "config.json").read_text())
    R.info("A", "launch settings still empty (set at launch, see PUBLISHING.md)", f"contact link: {cfgj['contact']['url'] or 'not set'}; site url: {cfgj['site_url'] or 'not set'}")


# ----------------------------------------------------------------------------------------------------------------------------- B
def first_commit() -> list[Path]:
    """What `git add .` would pick up, computed with a throwaway git directory so nothing is created in the project."""
    gd = Path(tempfile.mkdtemp())
    env = {**os.environ, "GIT_DIR": str(gd / "g"), "GIT_WORK_TREE": str(ROOT)}
    subprocess.run(["git", "init", "-q"], env=env, check=True, cwd=ROOT)
    out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], env=env, cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    shutil.rmtree(gd, ignore_errors=True)
    return [ROOT / x for x in out if x]


def repo(R):
    print("B. The repository")
    files = first_commit()
    total = sum(p.stat().st_size for p in files if p.exists())
    forbidden = [p for p in files if p.relative_to(ROOT).parts[0] in ("truth", "truth_live", "sources", "sources_live", "warehouse", "dist") or p.suffix in (".duckdb", ".parquet", ".xlsx", ".pkl")
                 or "dashboard/data" in p.relative_to(ROOT).as_posix()]
    R.add("B", "a first commit holds code and documents only: small, with no generated data and no answer key", f"{len(files):,} files, {total / 1e6:.1f} MB; forbidden files: {len(forbidden)}", "< 25 MB and none forbidden", total < 25e6 and not forbidden)
    hits = []
    for p in files:
        if p.suffix not in {".py", ".sql", ".yml", ".yaml", ".md", ".json", ".csv", ".js", ".html", ".css", ".toml", ".txt"} or p.stat().st_size > 3_000_000:
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        for pat in PRIVATE[8:]:
            m = re.search(pat, t)
            if m:
                hits.append(f"{p.relative_to(ROOT).as_posix()}: {m.group(0)[:30]}")
    R.add("B", "no keys or passwords in anything that would be committed", f"{len(hits)} matches over {len(files):,} files" + ("" if not hits else ": " + "; ".join(hits[:3])), "0", not hits)
    # clean-room import
    tmp = Path(tempfile.mkdtemp())
    for p in files:
        d = tmp / p.relative_to(ROOT)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)
    mods = sorted({".".join(p.relative_to(tmp).with_suffix("").parts) for p in tmp.rglob("*.py") if p.name != "__init__.py" and p.relative_to(tmp).parts[0] in ("generator", "pipeline", "tests")})
    code = "import importlib,sys\nbad=[]\nfor m in sys.argv[1:]:\n    try: importlib.import_module(m)\n    except Exception as e: bad.append(m+': '+type(e).__name__+' '+str(e)[:80])\nprint('\\n'.join(bad)); sys.exit(1 if bad else 0)"
    r = subprocess.run([sys.executable, "-c", code, *mods], cwd=tmp, capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    R.add("B", "every module imports from a clean copy of what would be committed (no hidden dependence on generated files)", f"{len(mods)} modules; failures: {r.stdout.strip() or 'none'}", "all import", r.returncode == 0)
    # requirements
    req = [ln.strip() for ln in (ROOT / "requirements.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    names = {ln.split("==")[0].lower().replace("_", "-") for ln in req}
    imported = set()
    for p in files:
        if p.suffix == ".py":
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Import):
                    imported |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    imported.add(n.module.split(".")[0])
    third = {m for m in imported if m not in sys.stdlib_module_names and m not in ("generator", "pipeline", "tests")}
    alias = {"duckdb": "duckdb", "numpy": "numpy", "pandas": "pandas", "pyarrow": "pyarrow", "openpyxl": "openpyxl", "matplotlib": "matplotlib", "pytest": "pytest"}
    notin = sorted(m for m in third if alias.get(m, m) not in names)
    R.add("B", "every dependency is pinned, and everything the code imports is listed", f"{len(req)} pinned lines (dbt-core, dbt-duckdb and pytest included: {all(x in names for x in ('dbt-core', 'dbt-duckdb', 'pytest'))}); imported but not listed: {notin or 'none'}",
          "all pinned with ==, none missing", all("==" in x for x in req) and not notin and all(x in names for x in ("dbt-core", "dbt-duckdb", "pytest")))
    # data dictionary
    c = duckdb.connect(str(ROOT / "warehouse" / "ops_hub.duckdb"), read_only=True)
    n = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('raw','staging','intermediate','core','quarantine','marts','ops','ref')").fetchone()[0]
    c.close()
    before = (DOCS / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    from . import data_dictionary
    data_dictionary.main()
    after = (DOCS / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    documented = len(re.findall(r"^### `", after, re.M))
    R.add("B", "the data dictionary documents every table and is current (regenerating changes nothing)", f"{documented} documented of {n} tables and views; unchanged on regeneration: {before == after}", "all, unchanged", documented == n and before == after)
    # documents
    need = ["README.md"] + [f"docs/{x}" for x in ("ARCHITECTURE.md", "DATA_DICTIONARY.md", "RUNBOOK.md", "PUBLISHING.md", "SPEC.md", "DEFECT_CATALOG.md")] + [f"docs/PHASE{i}_REPORT.md" for i in range(1, 9)]
    miss = [x for x in need if not (ROOT / x).exists()]
    broken = []
    for md in [ROOT / "README.md", *sorted(DOCS.glob("*.md"))]:
        for label, href in re.findall(r"\[([^\]]+)\]\(([^)#]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if href.startswith(("http", "mailto")):
                continue
            if not (md.parent / href).resolve().exists():
                broken.append(f"{md.name} -> {href}")
    R.add("B", "the documents exist and every link between them works", f"{len(need) - len(miss)} of {len(need)} required documents; {len(broken)} broken links" + ("" if not broken else ": " + ", ".join(broken[:4])), "none missing, none broken", not miss and not broken)
    return files


def write_report(R, files):
    st = lambda r: {"GATE": "PASS" if r[4] else "FAIL", "INFO": "INFO"}[r[5]]
    rows = "\n".join(f"| {n} | {m} | {cr} | {st((g, n, m, cr, ok, k))} |" for g, n, m, cr, ok, k in R.rows)
    gates = [r for r in R.rows if r[5] == "GATE"]
    txt = ["# System 1 — Phase 9 Report: Packaging\n",
           f"Gates: **{'ALL PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in gates)}/{len(gates)}). **Nothing has been published**: no repository, no host, no DNS, no upload. This phase makes the project ready to publish and says exactly what is left to decide.\n",
           "## What was built\n",
           "- **A public bundle** (`python -m pipeline.package`): the dashboard and its exported JSON, nothing else, deterministic, with cache and security headers, a robots file that keeps search engines out until launch, and a manifest of every file.\n",
           "- **A repository ready to be private** (`.gitignore`, complete pinned `requirements.txt`): a first commit would contain code and documents only. The answer key, generated sources, warehouse and bundle are excluded.\n",
           "- **Documents:** a rewritten README (set up, rebuild from nothing with timings, every gate, layout), `ARCHITECTURE.md` (the idea, data flow, the promise of each layer, decisions, limits), `DATA_DICTIONARY.md` (generated from the warehouse: every table and view), `PUBLISHING.md` (public and private, hosting, launch checklist, the open decisions), and the existing runbook and phase reports.\n",
           "- **Launch settings in one file:** `dashboard/config.json` holds the contact link and site URL, so launch needs no code change.\n",
           "## Open decisions (also in `PUBLISHING.md`)\n",
           "Subdomain and host; launch date (the generated year ends 2027-09-30); where the nightly state lives (a machine that stays on, a hosted runner with storage, or a stateless rebuild); the contact link for the call-to-action; whether to be searchable from day one; and whether to rename the placeholder company.\n",
           "## Honest notes\n",
           "- **The requirements file was incomplete until this phase.** It listed the numeric libraries but not the dbt packages or pytest, so a fresh install would not have been able to run the pipeline. It is now complete and checked against what the code imports.\n",
           "- **The clean-copy check caught a real mistake.** The first version of the ignore rules said `sources/`, which also hid `generator/sources/` (the five source builders), so a first commit would have been missing code. The rules are now anchored to the project root, and the gate imports every module from a copy of exactly what would be committed.\n",
           "- **The published scorecard shows all nine phases, including every miss.** Nothing was removed or reworded for the public view.\n",
           "- **Not tested here:** a real upload and a real domain, because nothing may be published without the owner's go-ahead; a rebuild from nothing on a second machine (the timings in the README are from this one).\n",
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (DOCS / "PHASE9_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def main():
    R = R7()
    bundle(R)
    files = repo(R)
    write_report(R, files)
    from . import export_scorecard
    export_scorecard.main()
    from pipeline import package
    package.build(DIST)  # the bundle now carries the Phase 9 results too
    gates = [r for r in R.rows if r[5] == "GATE"]
    print(f"\n{sum(r[4] for r in gates)}/{len(gates)} gates passed")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
