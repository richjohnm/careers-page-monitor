
import re
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import urljoin

Job = Dict[str, str]

def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

# Greenhouse

def parse_greenhouse(url: str, html: str, base_url: Optional[str]=None) -> List[Job]:
    soup = BeautifulSoup(html, 'lxml')
    jobs: List[Job] = []
    for div in soup.select('div.opening, div.opening a, a[data-mapped], a[href*="/jobs/"]'):
        a = div if getattr(div, 'name', None) == 'a' else div.find('a')
        if not a:
            continue
        title = _norm_space(a.get_text())
        href = a.get('href')
        job_url = urljoin(base_url or url, href)
        if title and href:
            jobs.append({'title': title, 'url': job_url})
    return jobs

# Lever

def parse_lever(url: str, html: str, base_url: Optional[str]=None) -> List[Job]:
    soup = BeautifulSoup(html, 'lxml')
    jobs: List[Job] = []
    for a in soup.select('a.posting-title, a[href*="/jobs/"]'):
        title = _norm_space(a.get_text())
        href = a.get('href')
        job_url = urljoin(base_url or url, href)
        if title and href:
            jobs.append({'title': title, 'url': job_url})
    return jobs

# Ashby (basic)

def parse_ashby(url: str, html: str, base_url: Optional[str]=None) -> List[Job]:
    soup = BeautifulSoup(html, 'lxml')
    jobs: List[Job] = []
    for a in soup.select('a[href*="/jobs/"], a[href*="/job/"], a[href*="/positions/"]'):
        title = _norm_space(a.get_text())
        href = a.get('href')
        job_url = urljoin(base_url or url, href)
        if title and href:
            jobs.append({'title': title, 'url': job_url})
    return jobs

# Workday (fallback to generic)

def parse_workday(url: str, html: str, base_url: Optional[str]=None) -> List[Job]:
    return parse_generic(url, html, base_url)

# Generic

def parse_generic(url: str, html: str, base_url: Optional[str]=None) -> List[Job]:
    soup = BeautifulSoup(html, 'lxml')
    jobs: List[Job] = []
    patterns = re.compile(r"jobs?|careers?|opportunit|opening|position|role", re.I)
    for a in soup.find_all('a', href=True):
        text = _norm_space(a.get_text())
        href = a['href']
        if patterns.search(text) or patterns.search(href):
            job_url = urljoin(base_url or url, href)
            if text:
                jobs.append({'title': text, 'url': job_url})
    return jobs

# Router

def select_parser(url: str):
    u = url.lower()
    if 'greenhouse.io' in u:
        return parse_greenhouse
    if 'lever.co' in u:
        return parse_lever
    if 'ashbyhq.com' in u or ('ashby' in u and '/jobs' in u):
        return parse_ashby
    if 'workday' in u or 'myworkdayjobs' in u:
        return parse_workday
    return parse_generic
