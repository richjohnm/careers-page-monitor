import csv
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict

import requests
import yaml

from .storage import Storage
from .notify import send_teams  # email removed
from .fetchers import (
    try_lever,
    try_greenhouse,
    try_workday_cxs,
    crawl_with_pagination,
    extract_jobs_from_html,
)


@dataclass
class Target:
    url: str
    company: str


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_keywords(path: str) -> List[str]:
    kws: List[str] = []
    if not os.path.exists(path):
        return kws
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                kws.append(s.lower())
    return kws


def load_targets(path: str) -> List[Target]:
    out: List[Target] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url or url.startswith("#"):
                continue
            out.append(
                Target(
                    url=url,
                    company=(row.get("company") or "").strip(),
                )
            )
    return out


def keyword_match(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    t = (text or "").lower()
    return any(kw in t for kw in keywords)


def hash_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
    return h.hexdigest()[:16]


def get_jobs_for_target(session: requests.Session, tgt: Target, cfg: dict) -> List[Dict]:
    # Prefer JSON APIs
    jobs = (
        try_workday_cxs(session, tgt.url)
        or try_lever(session, tgt.url)
        or try_greenhouse(session, tgt.url)
    )
    if jobs is None:
        max_pages = int(cfg.get("paging", {}).get("max_pages_per_site", 10))
        pages = crawl_with_pagination(session, tgt.url, max_pages)
        page_jobs: List[Dict] = []
        for page in pages:
            page_jobs.extend(extract_jobs_from_html(session, page))
        jobs = page_jobs

    keywords = load_keywords("scraper/keywords.txt")
    out: List[Dict] = []
    for j in jobs:
        title = j.get("title", "")
        url = j.get("url", "")
        if keyword_match(title, keywords):
            out.append(
                {
                    "title": title,
                    "url": url,
                    "company": tgt.company,
                    "location": j.get("location", ""),
                }
            )
    return out


def main():
    cfg = load_config("scraper/config.yaml")

    # Safe defaults to avoid KeyErrors if config keys are missing
    req_cfg = cfg.get("request", {})
    crawl_cfg = cfg.get("crawl", {})
    state_cfg = cfg.get("state", {})
    notif_cfg = cfg.get("notifications", {})

    user_agent = req_cfg.get(
        "user_agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0 Safari/537.36",
    )
    sleep_ms = int(req_cfg.get("sleep_between_requests_ms", 250))
    max_workers = int(crawl_cfg.get("max_workers", 8))
    db_path = state_cfg.get("db_path", "state/jobs.db")
    commit_state = str(state_cfg.get("commit_state_changes", True)).lower() == "true"

    targets = load_targets("scraper/urls.csv")

    headers = {"User-Agent": user_agent}
    session = requests.Session()
    session.headers.update(headers)

    storage = Storage(db_path)

    new_items: List[Dict] = []

    # Crawl concurrently
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for tgt in targets:
            futures.append(ex.submit(get_jobs_for_target, session, tgt, cfg))
            time.sleep(sleep_ms / 1000.0)
        for fut in as_completed(futures):
            try:
                items = fut.result()
                for it in items:
                    it["job_id"] = hash_id(it.get("url", ""), it.get("title", ""))
                    # upsert always; add to new_items only when first seen
                    first_seen = not storage.seen(it["job_id"])
                    storage.upsert(it)
                    if first_seen:
                        new_items.append(it)
            except Exception as e:
                print("Error during fetch:", e)

    print(f"Found {len(new_items)} new jobs.")

    # ---- Teams only ----
    enable_teams = str(notif_cfg.get("enable_teams", True)).lower() == "true"
    webhook = os.getenv("TEAMS_WEBHOOK_URL", "").strip()

    if new_items and enable_teams:
        if webhook:
            try:
                send_teams(webhook, "New jobs found", new_items)
                print("Sent Teams notification")
            except Exception as e:
                print("Teams notify failed:", e)
        else:
            print("TEAMS_WEBHOOK_URL not set; skipping Teams notification.")
    elif not new_items:
        print("No new items; no notification sent.")

    # ---- Commit state file changes when running in Actions (optional) ----
    in_actions = str(os.getenv("GITHUB_ACTIONS", "false")).lower() == "true"
    if in_actions and commit_state:
        try:
            import subprocess

            subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
            subprocess.run(
                ["git", "config", "user.email", "github-actions@github.com"], check=True
            )
            subprocess.run(["git", "add", db_path], check=True)
            status = subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True
            )
            if status.stdout.strip():
                subprocess.run(
                    ["git", "commit", "-m", "chore: update job state [skip ci]"],
                    check=True,
                )
                subprocess.run(["git", "push"], check=True)
                print("Committed state changes")
            else:
                print("No state changes to commit")
        except Exception as e:
            print("Commit/push skipped or failed:", e)


if __name__ == "__main__":
    main()

