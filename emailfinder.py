"""Free email finder: learns each company's email format, checks the domain takes mail,
and (where the mail server allows) checks the mailbox exists. No paid API needed."""
import json
import random
import re
import smtplib
import socket
import string
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser

import settings

PATTERNS = {
    "first.last": "{first}.{last}",
    "flast": "{f}{last}",
    "first": "{first}",
    "firstlast": "{first}{last}",
    "f.last": "{f}.{last}",
    "first_last": "{first}_{last}",
    "last.first": "{last}.{first}",
    "firstl": "{first}{l}",
    "first-last": "{first}-{last}",
    "last": "{last}",
}
# Most common corporate formats first.
DEFAULT_ORDER = ["first.last", "flast", "first", "firstlast", "f.last", "first_last", "last.first"]

HIRING_INBOXES = {"hr", "careers", "career", "jobs", "job", "recruitment", "recruiting", "recruit",
                  "talent", "hiring", "cv", "cvs", "resume", "people", "humanresources", "vacancies"}
GENERIC_INBOXES = HIRING_INBOXES | {"info", "contact", "contactus", "admin", "office", "sales", "enquiries",
                                    "enquiry", "inquiries", "hello", "mail", "support", "marketing", "media",
                                    "press", "webmaster", "procurement", "tenders", "general", "reception"}
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com",
             "aol.com", "yahoo.co.in", "rediffmail.com", "ymail.com", "proton.me", "protonmail.com"}

_mx_cache, _catchall_cache = {}, {}
_smtp_ok = [settings.VERIFY_MAILBOX_SMTP]


def _clean(name):
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", name)


def _name_parts(first, last):
    first = _clean((first or "").split(" ")[0])
    last = _clean(last or "")
    return first, last


def render(pattern, first, last):
    f, l = _name_parts(first, last)
    template = PATTERNS[pattern]
    if not f or (not l and ("{last}" in template or "{l}" in template)):
        return ""
    return template.format(first=f, last=l, f=f[:1], l=l[:1])


def is_generic(email):
    return email.split("@")[0].lower().replace(".", "").replace("-", "") in GENERIC_INBOXES


def is_hiring_inbox(email):
    return email.split("@")[0].lower().replace(".", "").replace("-", "") in HIRING_INBOXES


def domain_of(email):
    return email.split("@")[1].lower() if "@" in email else ""


def infer_pattern(email, first="", last=""):
    """Which format a real email uses. With the owner's name it's exact; without, a safe structural guess."""
    if not email or is_generic(email) or domain_of(email) in FREE_MAIL:
        return None
    local = email.split("@")[0].lower()
    if first and last:
        for name in PATTERNS:
            if render(name, first, last) == local:
                return name
        return None
    m = re.fullmatch(r"([a-z]+)([._-])([a-z]+)", local)
    if not m:
        return None
    a, sep, b = m.groups()
    if len(a) == 1 and sep == ".":
        return "f.last"
    return {".": "first.last", "_": "first_last", "-": "first-last"}[sep]


# ---------- Does the domain receive mail? ----------

def mx_hosts(domain):
    if domain in _mx_cache:
        return _mx_cache[domain]
    hosts = []
    try:
        url = "https://dns.google/resolve?" + urllib.parse.urlencode({"name": domain, "type": "MX"})
        with urllib.request.urlopen(url, timeout=10) as r:
            answers = json.load(r).get("Answer", [])
        recs = sorted((int(a["data"].split()[0]), a["data"].split()[1].rstrip(".")) for a in answers if a.get("type") == 15)
        hosts = [h for _, h in recs if h]
    except Exception:
        hosts = []
    _mx_cache[domain] = hosts
    return hosts


# ---------- Does the mailbox exist? (SMTP RCPT check, no email is sent) ----------

def _rcpt(mx, addresses):
    """Returns {address: True/False/None}. None = server wouldn't say."""
    out = {a: None for a in addresses}
    try:
        server = smtplib.SMTP(mx, 25, timeout=10)
        server.ehlo(settings.SMTP_HELO_DOMAIN)
        server.mail("")
        for a in addresses:
            code, _ = server.rcpt(a)
            if 200 <= code < 300:
                out[a] = True
            elif code in (550, 551, 553, 554):
                out[a] = False
        server.quit()
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        if isinstance(e, (socket.timeout, ConnectionRefusedError)) or "timed out" in str(e):
            _smtp_ok[0] = False  # port 25 blocked on this network: stop trying
    except smtplib.SMTPException:
        pass
    return out


def check_mailboxes(domain, candidates):
    """Returns (status, {email: True/False/None}). status: 'checked', 'accept-all', or 'unavailable'."""
    hosts = mx_hosts(domain)
    if not hosts or not _smtp_ok[0]:
        return "unavailable", {}
    import credits
    credits.USAGE["mailbox_checks"] += 1
    fake = "zz" + "".join(random.choice(string.ascii_lowercase) for _ in range(10)) + "@" + domain
    res = _rcpt(hosts[0], [fake] + candidates)
    if res.get(fake) is True:
        _catchall_cache[domain] = True
        return "accept-all", {}
    if res.get(fake) is None:
        return "unavailable", {}
    return "checked", {c: res.get(c) for c in candidates}


# ---------- Find a person's email ----------

def find_email(first, last, domain, known_pattern=None):
    """Returns (email, status). Status says how sure we are, best first:
    'verified' > 'pattern from real email' > 'best guess (common format)'."""
    domain = (domain or "").lower()
    if not domain:
        return "", "no company website"
    if domain in FREE_MAIL:
        return "", "company uses free email"
    if not mx_hosts(domain):
        return "", "domain doesn't receive email"
    order = ([known_pattern] if known_pattern else []) + [p for p in DEFAULT_ORDER if p != known_pattern]
    candidates = []
    for p in order:
        local = render(p, first, last)
        if local and local + "@" + domain not in candidates:
            candidates.append(local + "@" + domain)
    if not candidates:
        return "", "name too short to guess"
    if not known_pattern and domain not in _catchall_cache:
        status, results = check_mailboxes(domain, candidates[:settings.SMTP_MAX_GUESSES])
        if status == "checked":
            hit = next((c for c in candidates if results.get(c) is True), None)
            if hit:
                return hit, "verified"
    if known_pattern:
        return candidates[0], "pattern from real email"
    return candidates[0], "best guess (common format)"


# ---------- Public contact emails on the company website ----------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SITE_PAGES = ["", "contact", "contact-us", "careers", "about"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (contact lookup)"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read(800000).decode("utf-8", "ignore"), r.geturl()


def _brand(domain):
    return re.sub(r"[^a-z]", "", (domain or "").lower().replace("www.", "").split(".")[0])


def _same_company(email_domain, domain, final_url):
    """hr@danwayllc.com counts for danway.ae (same brand, group domains)."""
    if email_domain in FREE_MAIL:
        return False
    final_domain = urllib.parse.urlparse(final_url).netloc.replace("www.", "")
    if email_domain in (domain, final_domain) or email_domain.endswith("." + domain):
        return True
    brand = _brand(domain)
    return len(brand) >= 4 and brand in email_domain.replace("-", "")


def website_emails(domain):
    """Emails at the company's own domain published on its homepage, contact and careers pages."""
    if not domain or domain in FREE_MAIL:
        return []
    base = None
    for root in ("https://" + domain + "/", "https://www." + domain + "/"):
        try:
            home, final = _get(root)
            base = final.split("#")[0].rstrip("/") + "/"
            break
        except Exception:
            continue
    if not base:
        return []
    robots = urllib.robotparser.RobotFileParser()
    try:
        robots.parse(_get(base + "robots.txt")[0].splitlines())
    except Exception:
        robots.parse([])
    found, pages = [], {"": home}
    for page in SITE_PAGES[1:]:
        if robots.can_fetch("Mozilla/5.0", base + page):
            try:
                pages[page] = _get(base + page)[0]
            except Exception:
                pass
    for html in pages.values():
        for e in EMAIL_RE.findall(html):
            e = e.lower().strip(".")
            d = domain_of(e)
            if _same_company(d, domain, final) and mx_hosts(d) and not re.search(r"\.(png|jpe?g|gif|svg|webp)$", e) and e not in found:
                found.append(e)
    return found


# ---------- Company website from just a name (for Adzuna results) ----------

LEGAL_WORDS = {"ltd", "limited", "llc", "plc", "inc", "gmbh", "bv", "sa", "spa", "srl", "pvt", "private",
               "group", "holdings", "holding", "company", "co", "corp", "corporation", "ag", "nv", "the",
               "pte", "pty", "uk", "india", "services", "international"}
COUNTRY_TLDS = {"GB": [".co.uk"], "IN": [".in", ".co.in"], "SG": [".com.sg", ".sg"], "ZA": [".co.za"],
                "BR": [".com.br"], "NL": [".nl"], "DE": [".de"], "FR": [".fr"], "IT": [".it"],
                "ES": [".es"], "PL": [".pl"]}


BOT_WALL = re.compile(r"challenge validation|just a moment|captcha|access denied|attention required|are you a robot", re.I)


def guess_domain(company, country=""):
    """Tries likely domains (brand.com, brand.co.uk...) and keeps one that takes email and whose
    homepage mentions the company. Returns '' when unsure."""
    words = [w for w in re.findall(r"[a-z0-9]+", _clean_keep_digits(company)) if w not in LEGAL_WORDS]
    if not words:
        return ""
    slugs = ["".join(words)]
    if len(words) > 1 and len(words[0]) >= 4:
        slugs.append(words[0])
    if len(words) > 1:
        slugs.append("-".join(words))
    tlds = [".com"] + COUNTRY_TLDS.get(country, [])
    for slug in slugs:
        for tld in tlds:
            domain = slug + tld
            if not mx_hosts(domain):
                continue
            html, final = "", ""
            for url in ("https://www." + domain + "/", "https://" + domain + "/"):
                try:
                    html, final = _get(url)
                    break
                except Exception:
                    continue
            page = re.sub(r"\s+", " ", html[:200000].lower())
            if html and words[0] in page.replace("-", "") and not BOT_WALL.search(page[:3000]):
                return urllib.parse.urlparse(final).netloc.replace("www.", "") or domain
            # Site hides behind a bot check or won't load: trust an exact full-name match that takes email.
            if slug == slugs[0] and (not html or BOT_WALL.search(page[:3000])):
                return domain
    return ""


def _clean_keep_digits(name):
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
