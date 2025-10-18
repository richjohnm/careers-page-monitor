
import requests
import smtplib
from email.mime.text import MIMEText
from typing import List, Dict

def send_teams(webhook_url: str, headline: str, items: List[Dict]):
    if not webhook_url:
        return
    payload = {
        "headline": headline,
        "count": len(items),
        "items": [
            {"title": it.get('title'), "url": it.get('url'), "company": it.get('company'), "location": it.get('location')} 
            for it in items
        ]
    }
    resp = requests.post(webhook_url, json=payload, timeout=15)
    resp.raise_for_status()

def send_email(smtp_server: str, smtp_port: int, username: str, password: str,
               from_addr: str, to_addrs: str, subject: str, body: str):
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addrs
    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(from_addr, [a.strip() for a in to_addrs.split(',') if a.strip()], msg.as_string())
