"""Credit usage bars for each service, shown at the start and end of every run."""
import json
import os
from datetime import date, datetime

import providers

USAGE = {"theirstack_jobs": 0, "adzuna_calls": 0, "gemini_calls": 0, "mailbox_checks": 0, "website_lookups": 0}


def _bar(used, total, width=24):
    if not total:
        return "[" + "?" * width + "]"
    filled = min(width, int(round(width * used / float(total))))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def theirstack_balance():
    """Returns dict with used/total/left/renews, or None if it can't be read."""
    try:
        b = providers.theirstack_credit_balance()
    except providers.ProviderError:
        return None
    total, used = b.get("api_credits", 0), b.get("used_api_credits", 0)
    renews = (b.get("earliest_expiration") or "")[:10]
    return {"used": used, "total": total, "left": max(0, total - used), "renews": renews}


def _state_path(here):
    return os.path.join(here, "data", "usage_state.json")


def load_state(here):
    try:
        with open(_state_path(here)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(here, state):
    os.makedirs(os.path.join(here, "data"), exist_ok=True)
    with open(_state_path(here), "w") as f:
        json.dump(state, f, indent=1)


def record_run(here, apollo_blocked=None):
    """Adds this run's usage to today's totals."""
    state = load_state(here)
    today = date.today().isoformat()
    day = state.setdefault("days", {}).setdefault(today, {k: 0 for k in USAGE})
    for k, v in USAGE.items():
        day[k] = day.get(k, 0) + v
    if apollo_blocked is not None:
        state["apollo_people_api"] = "blocked on current plan" if apollo_blocked else "available"
    state["days"] = dict(sorted(state["days"].items())[-31:])
    save_state(here, state)
    return state


def report(here, title, ts=None):
    """Prints the usage panel and returns rows for 00_credit_usage.csv."""
    ts = ts if ts is not None else theirstack_balance()
    state = load_state(here)
    today = state.get("days", {}).get(date.today().isoformat(), {})
    rows = []
    print("\n" + "=" * 64)
    print(" CREDITS - %s (%s)" % (title, datetime.now().strftime("%d %b %H:%M")))
    print("=" * 64)
    if ts:
        status = "OUT OF CREDITS" if ts["left"] == 0 else ("LOW" if ts["left"] < 25 else "OK")
        print(" TheirStack jobs  %s %d/%d used | %d left | renews %s | %s"
              % (_bar(ts["used"], ts["total"]), ts["used"], ts["total"], ts["left"], ts["renews"], status))
        rows.append({"service": "TheirStack (job ads)", "used": ts["used"], "limit": ts["total"],
                     "left": ts["left"], "renews": ts["renews"], "status": status,
                     "note": "1 credit per job ad pulled"})
    else:
        print(" TheirStack jobs  %s balance unavailable (no key or no connection)" % _bar(0, 0))
        rows.append({"service": "TheirStack (job ads)", "status": "unknown", "note": "balance unavailable"})
    az_today = today.get("adzuna_calls", 0)
    if os.environ.get("ADZUNA_APP_ID"):
        print(" Adzuna jobs      %d searches today (free plan; daily and monthly limits apply)" % az_today)
        rows.append({"service": "Adzuna (backup job ads)", "used": az_today, "status": "free tier",
                     "note": "used when TheirStack is out of credits, or with --source adzuna"})
    else:
        print(" Adzuna jobs      not set up (add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env)")
    apollo = state.get("apollo_people_api", "not checked yet")
    print(" Apollo contacts  people API: %s" % apollo)
    rows.append({"service": "Apollo (contacts)", "status": apollo,
                 "note": "free plan has no API access to people; engine uses the free email finder instead"})
    keys = 1 + bool(os.environ.get("GEMINI_API_KEY_BACKUP"))
    print(" Gemini writing   %d AI calls today (%d key%s; if the daily free limit is hit, the backup key"
          % (today.get("gemini_calls", 0), keys, "s" if keys > 1 else ""))
    print("                  takes over, then the built-in templates)")
    rows.append({"service": "Gemini (writing)", "used": today.get("gemini_calls", 0), "status": "free tier",
                 "note": "Google doesn't publish a balance; usage counted locally"})
    print(" Email finder     %d mailbox checks, %d website lookups today | free, no limit"
          % (today.get("mailbox_checks", 0), today.get("website_lookups", 0)))
    rows.append({"service": "Email finder (mailbox check + websites)", "used": today.get("mailbox_checks", 0),
                 "status": "free", "note": "no credits"})
    print("=" * 64 + "\n")
    return rows
