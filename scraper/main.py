
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
from .notify import send_teams, send_email
from .fetchers import try_lever, try_greenhouse, try_workday_cxs, crawl_with_pagination, extract_jobs_from_html

@dataclass
class Target:
    url: str
    company: str


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_keywords(path: str) -> List[str]:
    kws = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#'):
                kws.append(s.lower())
    return kws


def load_targets(path: str) -> List[Target]:
    out: List[Target] = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['url'].strip().startswith('#') or not row['url'].strip():
                continue
            out.append(Target(url=row['url'].strip(), company=row.get('company', '').strip()))
    return out


def keyword_match(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    t = (text or '').lower()
    return any(kw in t for kw in keywords)


def hash_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or '').encode('utf-8'))
    return h.hexdigest()[:16]


def get_jobs_for_target(session: requests.Session, tgt: Target, cfg: dict) -> List[Dict]:
    # Prefer JSON APIs
    jobs = try_workday_cxs(session, tgt.url) or try_lever(session, tgt.url) or try_greenhouse(session, tgt.url)
    if jobs is None:
        pages = crawl_with_pagination(session, tgt.url, cfg.get('paging',{}).get('max_pages_per_site',10))
        page_jobs: List[Dict] = []
        for page in pages:
            page_jobs.extend(extract_jobs_from_html(session, page))
        jobs = page_jobs

    keywords = load_keywords('scraper/keywords.txt')
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

    headers = {'User-Agent': cfg['request']['user_agent']}
    session = requests.Session()
    session.headers.update(headers)

    storage = Storage(cfg['state']['db_path'])

    new_items: List[Dict] = []

    with ThreadPoolExecutor(max_workers=cfg['crawl']['max_workers']) as ex:
        futures = []
        for tgt in targets:
            futures.append(ex.submit(get_jobs_for_target, session, tgt, cfg))
            time.sleep(cfg['request']['sleep_between_requests_ms']/1000.0)
        for fut in as_completed(futures):
            try:
                items = fut.result()
                for it in items:
                    it['job_id'] = hash_id(it['url'], it['title'])
                    if not storage.seen(it['job_id']):
                        storage.upsert(it)
                        new_items.append(it)
                    else:
                        storage.upsert(it)
            except Exception as e:
                print('Error:', e)

    print(f"Found {len(new_items)} new jobs.")

    if new_items:
        if os.getenv('TEAMS_WEBHOOK_URL') and str(cfg['notifications'].get('enable_teams', True)).lower() == 'true':
            try:
                send_teams(os.getenv('TEAMS_WEBHOOK_URL'), 'New jobs found', new_items)
                print('Sent Teams notification')
            except Exception as e:
                print('Teams notify failed:', e)

        if str(cfg['notifications'].get('enable_email', False)).lower() == 'true':
            required = ['SMTP_SERVER','SMTP_PORT','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM','SMTP_TO']
            if all(os.getenv(k) for k in required):
                body_lines = [f"{it.get('title', 'Untitled')}\n{it.get('location', '')}" for it in items]
{it.get('company','')}
{it.get('url')}
" for it in new_items]
                body = "

".join(body_lines)
                try:
                    send_email(
                        os.getenv('SMTP_SERVER'),
                        int(os.getenv('SMTP_PORT')),
                        os.getenv('SMTP_USERNAME'),
                        os.getenv('SMTP_PASSWORD'),
                        os.getenv('SMTP_FROM'),
                        os.getenv('SMTP_TO'),
                        subject='New jobs found',
                        body=body
                    )
                    print('Sent email notification')
                except Exception as e:
                    print('Email notify failed:', e)
            else:
                print('Email not sent: missing SMTP_* environment variables')

    if os.getenv('GITHUB_ACTIONS','false').lower() == 'true' and str(cfg['state'].get('commit_state_changes', True)).lower() == 'true':
        try:
            import subprocess
            subprocess.run(['git','config','user.name','github-actions'], check=True)
            subprocess.run(['git','config','user.email','github-actions@github.com'], check=True)
            subprocess.run(['git','add', cfg['state']['db_path']], check=True)
            status = subprocess.run(['git','status','--porcelain'], capture_output=True, text=True)
            if status.stdout.strip():
                subprocess.run(['git','commit','-m','chore: update job state [skip ci]'], check=True)
                subprocess.run(['git','push'], check=True)
                print('Committed state changes')
            else:
                print('No state changes to commit')
        except Exception as e:
            print('Commit/push skipped or failed:', e)


if __name__ == '__main__':
    main()
