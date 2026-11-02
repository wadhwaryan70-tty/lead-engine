"""Remembers who got a draft, so the next run doesn't write to them again too soon."""
import csv
import os
from datetime import date, datetime

FIELDS = ["key", "first_name", "last_name", "company", "email", "linkedin_url", "pitch", "drafted_on"]


def contact_key(c):
    return (c.get("email") or c.get("linkedin_url") or "").strip().lower()


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["key"]: r for r in csv.DictReader(f) if r.get("key")}


def recently_drafted(history, contact, within_days):
    rec = history.get(contact_key(contact))
    if not rec:
        return False
    try:
        drafted = datetime.strptime(rec["drafted_on"], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (date.today() - drafted).days < within_days


def record(path, message_rows):
    history = load(path)
    today = date.today().isoformat()
    for r in message_rows:
        key = contact_key(r)
        if key:
            history[key] = {"key": key, "first_name": r["first_name"], "last_name": r["last_name"],
                            "company": r["company"], "email": r["email"], "linkedin_url": r["linkedin_url"],
                            "pitch": r["pitch"], "drafted_on": today}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(history.values())
