"""Thin clients for TheirStack (jobs), Apollo (people) and Gemini (writing). Stdlib only."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


class ProviderError(Exception):
    pass


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _request(method, url, headers, body=None, retries=3):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise ProviderError("%s %s -> HTTP %s: %s" % (method, url.split("?")[0], e.code, detail))
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            raise ProviderError("%s %s -> %s" % (method, url.split("?")[0], e.reason))


def require_key(name):
    key = os.environ.get(name, "").strip()
    if not key:
        raise ProviderError("%s is missing. Add it to the .env file." % name)
    return key


# ---------- TheirStack: open roles with posting dates ----------

def theirstack_search_jobs(filters, limit, page=0):
    key = require_key("THEIRSTACK_API_KEY")
    body = dict(filters, limit=limit, page=page)
    return _request(
        "POST", "https://api.theirstack.com/v1/jobs/search",
        {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        body,
    )


def theirstack_credit_balance():
    key = require_key("THEIRSTACK_API_KEY")
    return _request("GET", "https://api.theirstack.com/v0/billing/credit-balance",
                    {"Authorization": "Bearer " + key})


# ---------- Adzuna: free backup job source ----------

def adzuna_search(country, page, params):
    app_id, app_key = require_key("ADZUNA_APP_ID"), require_key("ADZUNA_APP_KEY")
    query = dict(params, app_id=app_id, app_key=app_key)
    query["content-type"] = "application/json"
    url = "https://api.adzuna.com/v1/api/jobs/%s/search/%d?%s" % (country.lower(), page, urllib.parse.urlencode(query))
    return _request("GET", url, {"Accept": "application/json"})


# ---------- Apollo: decision-makers, emails, LinkedIn ----------

def _apollo_headers():
    return {"x-api-key": require_key("APOLLO_API_KEY"),
            "Content-Type": "application/json", "Cache-Control": "no-cache"}


def apollo_search_people(domain, titles, per_page):
    """Free search (0 credits). Returns people without emails."""
    params = [("q_organization_domains_list[]", domain), ("per_page", per_page), ("page", 1)]
    params += [("person_titles[]", t) for t in titles]
    url = "https://api.apollo.io/api/v1/mixed_people/api_search?" + urllib.parse.urlencode(params)
    return _request("POST", url, _apollo_headers()).get("people", [])


def apollo_enrich_person(person_id=None, linkedin_url=None):
    """Reveals work email + LinkedIn. Uses Apollo credits."""
    params = {"reveal_personal_emails": "false"}
    if person_id:
        params["id"] = person_id
    if linkedin_url:
        params["linkedin_url"] = linkedin_url
    url = "https://api.apollo.io/api/v1/people/match?" + urllib.parse.urlencode(params)
    return _request("POST", url, _apollo_headers()).get("person") or {}


# ---------- Gemini: message writing ----------

def gemini_json(prompt, model):
    keys = [require_key("GEMINI_API_KEY")]
    if os.environ.get("GEMINI_API_KEY_BACKUP", "").strip():
        keys.append(os.environ["GEMINI_API_KEY_BACKUP"].strip())
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
    }
    import credits
    credits.USAGE["gemini_calls"] += 1
    for i, key in enumerate(keys):
        try:
            resp = _request("POST", url, {"x-goog-api-key": key, "Content-Type": "application/json"}, body)
            break
        except ProviderError as e:
            # Rate-limited or quota used up: try the backup key.
            if i == len(keys) - 1 or not any(c in str(e) for c in ("429", "403", "RESOURCE_EXHAUSTED")):
                raise
    try:
        parts = resp["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return json.loads(text)
    except (KeyError, IndexError, ValueError) as e:
        raise ProviderError("Gemini returned an unexpected response: %s" % e)
