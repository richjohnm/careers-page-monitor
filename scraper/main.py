import csv
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict

import requests
import yaml

# Email-related imports removed. Assuming send_teams is in .notify
from .storage import Storage
from .notify import send_teams
from .fetchers import try_lever, try_greenhouse, try_workday_cxs, crawl_with_pagination, extract_jobs_from_html

@dataclass
class Target:
    url: str
    company: str


def load_config(path: str) -> dict:
    """Loads configuration from a YAML file."""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_keywords(path: str) -> List[str]:
    """Loads keywords from a text file, ignoring comments and stripping whitespace."""
    kws = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith('#'):
                    kws.append(s.lower())
    except FileNotFoundError:
        print(f"Warning: Keywords file not found at {path}. Proceeding without keyword filtering.")
    return kws


def load_targets(path: str) -> List[Target]:
    """Loads target URLs and companies from a CSV file."""
    out: List[Target] = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row['url'].strip()
            # Skip commented out or empty URLs
            if url.startswith('#') or not url:
                continue
            out.append(Target(url=url, company=row.get('company', '').strip()))
    return out


def keyword_match(text: str, keywords: List[str]) -> bool:
    """Checks if any keyword is present in the text."""
    if not keywords:
        return True
    t = (text or '').lower()
    return any(kw in t for kw in keywords)


def hash_id(*parts: str) -> str:
    """Generates a consistent 16-character SHA256 hash for an item."""
    h = hashlib.sha256()
    for p in parts:
        h.update((p or '').encode('utf-8'))
    return h.hexdigest()[:16]


def get_jobs_for_target(tgt: Target, cfg: dict, headers: dict, keywords: List[str]) -> List[Dict]:
    """
    Worker function: Fetches jobs for a single target company.
    A new requests.Session is created for thread safety.
    """
    # FIX: Create a new requests.Session for thread safety
    session = requests.Session()
    session.headers.update(headers)
    
    jobs = None
    try:
        # Prefer JSON APIs (Workday, Lever, Greenhouse)
        jobs = try_workday_cxs(session, tgt.url) or try_lever(session, tgt.url) or try_greenhouse(session, tgt.url)

        if jobs is None:
            # Fallback to HTML crawling/pagination
            max_pages = cfg.get('paging',{}).get('max_pages_per_site', 10)
            pages = crawl_with_pagination(session, tgt.url, max_pages)
            page_jobs: List[Dict] = []
            for page in pages:
                page_jobs.extend(extract_jobs_from_html(session, page))
            jobs = page_jobs
            
    except Exception as e:
        print(f"Error fetching jobs for {tgt.company} ({tgt.url}): {e}")
        return []

    if jobs is None:
        jobs = []

    out = []
    for j in jobs:
        title = j.get('title','')
        url = j.get('url','')
        
        if keyword_match(title, keywords):
            out.append({
                'title': title,
                'url': url,
                'company': tgt.company,
                'location': j.get('location','')
            })
            
    return out


def main():
    cfg = load_config('scraper/config.yaml')
    targets = load_targets('scraper/urls.csv')
    # FIX: Load keywords once for efficiency
    keywords = load_keywords('scraper/keywords.txt')

    headers = {'User-Agent': cfg['request']['user_agent']}
    
    storage = Storage(cfg['state']['db_path'])

    new_items: List[Dict] = []
    
    max_workers = cfg['crawl']['max_workers']

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for i, tgt in enumerate(targets):
            # Pass config/data needed by the worker (headers, keywords)
            # FIX: Removed the shared session object
            futures.append(ex.submit(get_jobs_for_target, tgt, cfg, headers, keywords))
            
            # FIX: Removed time.sleep() from here to allow rapid task submission

        for fut in as_completed(futures):
            try:
                items = fut.result()
                for it in items:
                    it['job_id'] = hash_id(it['url'], it['title'])
                    
                    is_new = not storage.seen(it['job_id'])
                    
                    # FIX: Simplified upsert logic. Always upsert.
                    storage.upsert(it) 
                    
                    if is_new:
                        new_items.append(it)
                        
            except Exception as e:
                print(f'Error processing results for a target: {e}')

    print(f"Found {len(new_items)} new jobs.")

    # --- NOTIFICATIONS SECTION ---
    
    if new_items:
        # TE
