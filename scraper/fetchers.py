
import re
from urllib.parse import urlparse, urljoin, parse_qs, urlencode, urlunparse
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

Job = Dict[str, str]

def _norm_space(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", (s or '').strip())

# Lever JSON

def try_lever(session: requests.Session, url: str) -> Optional[List[Job]]:
    u = urlparse(url)
    if 'lever.co' not in u.netloc:
        return None
    parts = [p for p in u.path.split('/') if p]
    if not parts:
        return None
    company = parts[0]
    api = f"https://api.lever.co/v0/postings/{company}"
    r = session.get(api, timeout=20)
    if r.status_code != 200:
        return None
    jobs: List[Job] = []
    for item in r.json():
        title = item.get('text') or item.get('title')
        hosted_url = item.get('hostedUrl') or item.get('applyUrl') or item.get('url')
        if title and hosted_url:
            jobs.append({'title': _norm_space(title), 'url': hosted_url})
    return jobs

# Greenhouse JSON

def try_greenhouse(session: requests.Session, url: str) -> Optional[List[Job]]:
    u = urlparse(url)
    if 'greenhouse.io' not in u.netloc:
        return None
    parts = [p for p in u.path.split('/') if p]
    if not parts:
        return None
    token = parts[0]
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = session.get(api, timeout=20)
    if r.status_code != 200:
        return None
    jobs: List[Job] = []
    for it in r.json().get('jobs', []):
        title = it.get('title')
        url = it.get('absolute_url')
        if title and url:
            jobs.append({'title': _norm_space(title), 'url': url})
    return jobs

# Workday careers JSON (CXS) — best effort

def try_workday_cxs(session: requests.Session, url: str, page_size: int = 20, max_pages: int = 50) -> Optional[List[Job]]:
    u = urlparse(url)
    if '.myworkdayjobs.com' not in u.netloc:
        return None
    tenant = u.netloc.split('.')[0]
    path_parts = [p for p in u.path.split('/') if p]
    if not path_parts:
        return None
    site = path_parts[0]
    cxs = f"https://{u.netloc}/wday/cxs/{tenant}/{site}/jobs"
    jobs: List[Job] = []
    offset = 0
    pages = 0
    headers = {'Content-Type': 'application/json','Accept':'application/json'}
    while pages < max_pages:
        payload = {"limit": page_size, "offset": offset, "searchText": "", "appliedFacets": {}}
        r = session.post(cxs, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        items = data.get('jobPostings', [])
        if not items:
            break
        for it in items:
            title = it.get('title')
            path = it.get('externalPath') or it.get('canonicalPositionUri')
            if title and path:
                jobs.append({'title': _norm_space(title), 'url': f"https://{u.netloc}{path}"})
        offset += page_size
        pages += 1
    return jobs if jobs else None

# Generic HTML + pagination

def crawl_with_pagination(session: requests.Session, url: str, max_pages: int) -> List[str]:
    seen = set()
    to_visit = [url]
    pages = []
    while to_visit and len(pages) < max_pages:
        cur = to_visit.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        try:
            r = session.get(cur, timeout=30)
            if r.status_code != 200:
                continue
            pages.append(cur)
            soup = BeautifulSoup(r.text, 'lxml')
            a_next = soup.select_one('a[rel="next"]')
            cand = []
            if a_next and a_next.get('href'):
                cand.append(urljoin(cur, a_next['href']))
            for a in soup.find_all('a', href=True):
                txt = _norm_space(a.get_text()).lower()
                if txt in {'next','next ›','older','more'} or txt.endswith('»') or txt == '>':
                    cand.append(urljoin(cur, a['href']))
            # Heuristic: add page=n
            u2 = urlparse(cur)
            qs = parse_qs(u2.query)
            for key in ['page','Page','p','pg']:
                if key in qs:
                    try:
                        n = int(qs[key][0]) + 1
                        qs[key] = [str(n)]
                        new_q = urlencode(qs, doseq=True)
                        cand.append(urlunparse((u2.scheme,u2.netloc,u2.path,u2.params,new_q,u2.fragment)))
                    except Exception:
                        pass
            for nxt in cand:
                if nxt not in seen and nxt not in to_visit and len(pages)+len(to_visit) < max_pages:
                    to_visit.append(nxt)
        except Exception:
            continue
    return pages


def extract_jobs_from_html(session: requests.Session, page_url: str) -> List[Job]:
    r = session.get(page_url, timeout=30)
    r.raise_for_status()
    from .parsers import select_parser
    parser = select_parser(page_url)
    return parser(page_url, r.text, page_url)
