"""Steps 1-3: find stale open roles, find decision-makers, clean old prospects."""
import csv
import glob
import json
import os
import re
import urllib.parse
from collections import OrderedDict
from datetime import date, datetime, timedelta

import credits
import emailfinder
import providers
import settings


def _days_open(date_posted):
    try:
        posted = datetime.strptime(date_posted[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    return (date.today() - posted).days


def _domain(value):
    value = (value or "").lower().strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.split("/")[0]


def track_for_title(title):
    if re.search(settings.PERMANENT_TRACK_PATTERN, title or "", re.I):
        return "permanent"
    return "deputation"


# ---------- Step 1: open roles 30+ days old ----------

def find_open_roles(log, countries=None):
    today = date.today()
    filters = {
        "posted_at_lte": (today - timedelta(days=settings.MIN_DAYS_OPEN)).isoformat(),
        "posted_at_gte": (today - timedelta(days=settings.MAX_DAYS_OPEN)).isoformat(),
        "job_country_code_or": countries or settings.all_target_countries(),
        "job_country_code_not": settings.EXCLUDED_COUNTRIES,
        "job_title_or": settings.CRITICAL_ROLE_TITLES,
        "job_title_not": settings.EXCLUDED_TITLE_WORDS,
        "job_description_pattern_or": settings.SECTOR_PATTERNS,
        "industry_id_or": settings.CLIENT_INDUSTRY_IDS,
        "industry_id_not": settings.EXCLUDED_INDUSTRY_IDS,
    }
    roles, page, skipped_agencies, fetched = [], 0, 0, 0
    while fetched < settings.JOBS_PER_RUN:
        batch = settings.JOBS_PAGE_SIZE
        resp = providers.theirstack_search_jobs(filters, limit=batch, page=page)
        data = resp.get("data", [])
        if not data:
            break
        data = data[:settings.JOBS_PER_RUN - fetched]
        fetched += len(data)
        credits.USAGE["theirstack_jobs"] += len(data)
        for job in data:
            country = job.get("country_code") or ""
            company_obj = job.get("company_object") or {}
            company_name = job.get("company") or company_obj.get("name", "")
            if country in settings.EXCLUDED_COUNTRIES:
                continue
            if re.search(settings.EXCLUDED_COMPANY_NAME, company_name, re.I):
                skipped_agencies += 1
                continue
            hiring_team = job.get("hiring_team") or []
            roles.append({
                "company": company_name,
                "company_domain": _domain(job.get("company_domain") or company_obj.get("domain")),
                "company_industry": company_obj.get("industry") or "",
                "company_size": company_obj.get("employee_count") or "",
                "company_linkedin": company_obj.get("linkedin_url") or "",
                "ad_contact_emails": ", ".join(_emails_in(job.get("description"))),
                "job_title": job.get("job_title", ""),
                "country_code": country,
                "region": settings.region_for(country),
                "location": job.get("location") or "",
                "date_posted": (job.get("date_posted") or "")[:10],
                "days_open": _days_open(job.get("date_posted")),
                "job_url": job.get("url") or "",
                "ad_snippet": _snippet(job.get("description")),
                "hiring_team": "; ".join(
                    "%s (%s) %s" % (h.get("full_name", ""), h.get("role", ""), h.get("linkedin_url", ""))
                    for h in hiring_team),
                "_hiring_team_raw": hiring_team,
            })
        log("  fetched %d roles (page %d)" % (len(data), page))
        page += 1
        if len(data) < batch:
            break
    if skipped_agencies:
        log("  left out %d ads posted by recruitment agencies or anonymous advertisers" % skipped_agencies)
    roles.sort(key=lambda r: r["days_open"] if r["days_open"] != "" else 0, reverse=True)
    return roles


def find_open_roles_adzuna(log, countries=None):
    """Free backup source. Adzuna can't filter by minimum age, so we ask for the oldest ads first
    within MAX_DAYS_OPEN and keep the ones open 30+ days."""
    wanted = countries or settings.all_target_countries()
    covered = [c for c in wanted if c in settings.ADZUNA_COUNTRIES]
    if not covered:
        log("  Adzuna doesn't cover %s" % ", ".join(wanted))
        return []
    roles, calls, skipped = [], 0, 0
    for country in covered:
        for use_category in (True, False):
            got_any = False
            for page in range(1, settings.ADZUNA_PAGES_PER_COUNTRY + 1):
                if calls >= settings.ADZUNA_MAX_CALLS_PER_RUN:
                    break
                params = {"results_per_page": 50, "max_days_old": settings.MAX_DAYS_OPEN,
                          "sort_by": "date", "sort_dir": "up"}
                if use_category:
                    params["category"] = settings.ADZUNA_CATEGORY
                else:
                    params["what_or"] = settings.ADZUNA_KEYWORDS
                params["what_exclude"] = " ".join(settings.EXCLUDED_TITLE_WORDS)
                resp = providers.adzuna_search(country, page, params)
                calls += 1
                credits.USAGE["adzuna_calls"] += 1
                results = resp.get("results", [])
                for job in results:
                    days = _days_open(job.get("created"))
                    if days == "" or days < settings.MIN_DAYS_OPEN:
                        continue
                    company = (job.get("company") or {}).get("display_name", "")
                    text = (job.get("title") or "") + " " + (job.get("description") or "")
                    if not company or re.search(settings.EXCLUDED_COMPANY_NAME, company, re.I):
                        skipped += 1
                        continue
                    # Keyword searches are loose ("gas" matches boiler engineers), so check the text.
                    if not use_category and not any(re.search(p, text, re.I) for p in settings.SECTOR_PATTERNS):
                        continue
                    got_any = True
                    roles.append({
                        "company": company, "company_domain": "", "company_industry": "",
                        "company_size": "", "company_linkedin": "",
                        "ad_contact_emails": ", ".join(_emails_in(job.get("description"))),
                        "job_title": job.get("title", ""), "country_code": country,
                        "region": settings.region_for(country),
                        "location": (job.get("location") or {}).get("display_name", ""),
                        "date_posted": (job.get("created") or "")[:10], "days_open": days,
                        "job_url": job.get("redirect_url", ""), "hiring_team": "", "_hiring_team_raw": [],
                        "source": "Adzuna",
                    })
                if len(results) < 50:
                    break
            if got_any:
                break  # the category search worked for this country; no need for keywords
        log("  Adzuna %s: %d roles so far (%d calls)" % (country, len(roles), calls))
    if skipped:
        log("  left out %d ads posted by recruitment agencies or anonymous advertisers" % skipped)
    roles.sort(key=lambda r: r["days_open"], reverse=True)
    return roles


def resolve_missing_domains(companies, log):
    """Adzuna gives company names only; find the website so the email finder can work."""
    found = 0
    for c in companies[:settings.MAX_COMPANIES_PER_RUN]:
        if c.get("company_domain"):
            continue
        country = (c.get("countries") or "").split(",")[0].strip()
        domain = emailfinder.guess_domain(c["company"], country)
        if domain:
            c["company_domain"] = domain
            found += 1
    log("  found websites for %d companies" % found)


def _snippet(text, limit=500):
    """Start of the job ad, kept as evidence for the writer (what the ad actually says)."""
    text = re.sub(r"[#*_>`|]+", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Addresses in ads that aren't for hiring (ethics hotlines, privacy, fraud warnings...).
JUNK_EMAIL = re.compile(r"noreply|no-reply|donotreply|example\.|\.(png|jpe?g|gif|svg|webp)$|sentry|wixpress|"
                        r"^(ethics|compliance|privacy|dataprotection|data\.protection|gdpr|dpo|legal|fraud|"
                        r"security|accessibility|accommodation|accommodations|whistleblow|speakup|abuse)", re.I)


def _emails_in(text):
    """Contact emails written in the job ad, e.g. 'send your CV to hr@company.com'."""
    found = []
    for e in EMAIL_RE.findall(text or ""):
        e = e.strip(".").lower()
        if not JUNK_EMAIL.search(e) and e not in found and emailfinder.mx_hosts(emailfinder.domain_of(e)):
            found.append(e)
    return found


def _xray_link(company, titles):
    q = 'site:linkedin.com/in "%s" (%s)' % (company, " OR ".join('"%s"' % t for t in titles))
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": q})


def summarise_companies(roles):
    companies = OrderedDict()
    for r in roles:
        key = r["company_domain"] or r["company"].lower()
        c = companies.setdefault(key, {
            "company": r["company"], "company_domain": r["company_domain"],
            "industry": r.get("company_industry", ""), "employees": r.get("company_size", ""),
            "company_linkedin": r.get("company_linkedin", ""),
            "open_roles_30plus": 0, "oldest_days_open": 0, "countries": set(),
            "regions": set(), "sample_roles": [], "ad_contact_emails": [], "_hiring_team": [], "_signals": [],
        })
        if len(c["_signals"]) < 5:
            # Verified buying signals: each has a source (the job ad) and a date.
            c["_signals"].append({"role": r["job_title"], "country": r["country_code"], "days_open": r["days_open"],
                                  "date_posted": r.get("date_posted", ""), "url": r.get("job_url", ""),
                                  "location": r.get("location", ""), "snippet": r.get("ad_snippet", "")})
        for e in (r.get("ad_contact_emails") or "").split(", "):
            if e and e not in c["ad_contact_emails"]:
                c["ad_contact_emails"].append(e)
        c["open_roles_30plus"] += 1
        c["oldest_days_open"] = max(c["oldest_days_open"], r["days_open"] or 0)
        c["countries"].add(r["country_code"])
        if r["region"]:
            c["regions"].add(r["region"])
        if len(c["sample_roles"]) < 5:
            c["sample_roles"].append("%s (%s, %s days)" % (r["job_title"], r["country_code"], r["days_open"]))
        c["_hiring_team"].extend(r["_hiring_team_raw"])
    out = []
    for c in companies.values():
        # Priority: many stale roles and very old roles = biggest pain.
        c["priority_score"] = c["open_roles_30plus"] * 10 + min(c["oldest_days_open"], 120)
        c["countries"] = ", ".join(sorted(c["countries"]))
        c["regions"] = ", ".join(sorted(c["regions"]))
        c["sample_roles"] = " | ".join(c["sample_roles"])
        c["named_hiring_contacts"] = len(c["_hiring_team"])
        c["find_hr_on_google"] = _xray_link(c["company"], settings.DECISION_MAKER_TITLES["permanent"][:5])
        c["find_project_leads_on_google"] = _xray_link(c["company"], settings.DECISION_MAKER_TITLES["deputation"][:5])
        c["find_people_on_linkedin"] = ("https://www.linkedin.com/search/results/people/?" +
                                        urllib.parse.urlencode({"keywords": '"%s" (HR OR "talent acquisition" OR "project director")' % c["company"]}))
        out.append(c)
    out.sort(key=lambda c: c["priority_score"], reverse=True)
    return out


# ---------- Step 2: decision-makers with email + LinkedIn ----------

def _contact_row(person, company, source):
    org = person.get("organization") or {}
    title = person.get("title") or ""
    country = person.get("country") or ""
    return {
        "first_name": person.get("first_name") or "",
        "last_name": person.get("last_name") or "",
        "title": title,
        "company": org.get("name") or company["company"],
        "company_domain": company["company_domain"],
        "email": person.get("email") or "",
        "email_status": person.get("email_status") or "",
        "linkedin_url": person.get("linkedin_url") or "",
        "person_country": country,
        "track": track_for_title(title),
        "open_roles_30plus": company["open_roles_30plus"],
        "oldest_days_open": company["oldest_days_open"],
        "role_countries": company["countries"],
        "sample_roles": company["sample_roles"],
        "signals": json.dumps(company.get("_signals", [])),
        "industry": company.get("industry", ""),
        "lead_type": "new",
        "source": source,
    }


APOLLO_BLOCKED = None  # set when Apollo says the plan has no people API


def _plan_blocked(err):
    global APOLLO_BLOCKED
    blocked = "API_INACCESSIBLE" in str(err) or "not included in your" in str(err)
    if blocked:
        APOLLO_BLOCKED = True
    return blocked


def find_decision_makers(companies, log, use_apollo=True):
    """Without Apollo, only the hiring team named on job ads is returned (LinkedIn, no email)."""
    contacts, seen = [], set()
    titles = settings.DECISION_MAKER_TITLES["permanent"] + settings.DECISION_MAKER_TITLES["deputation"]
    for company in companies[:settings.MAX_COMPANIES_PER_RUN]:
        found = 0
        # The email printed in the job ad is the inbox that owns the vacancy: free and warm.
        for email in company.get("ad_contact_emails", [])[:2]:
            if email in seen:
                continue
            seen.add(email)
            contacts.append(dict(_contact_row({"title": "Hiring contact (email from job ad)", "email": email},
                                              company, "email in job ad"),
                                 track="permanent", email_status="from job ad"))
        # Hiring-team members named on the job ad come next: they own the vacancy.
        for member in company["_hiring_team"]:
            li = member.get("linkedin_url")
            if not li or li in seen or found >= settings.DECISION_MAKERS_PER_COMPANY:
                continue
            person = {}
            if use_apollo:
                try:
                    person = providers.apollo_enrich_person(linkedin_url=li)
                except providers.ProviderError as e:
                    if _plan_blocked(e):
                        log("  Apollo's plan doesn't include the people API; continuing with job-ad contacts only")
                        use_apollo = False
                    else:
                        log("  enrich failed for %s: %s" % (li, e))
            if not person:
                name = (member.get("full_name") or "").split(" ", 1)
                person = {"first_name": name[0], "last_name": name[1] if len(name) > 1 else "",
                          "title": member.get("role", ""), "linkedin_url": li}
            seen.add(li)
            contacts.append(_contact_row(person, company, "job ad hiring team"))
            found += 1
        if not use_apollo:
            log("  %s: %d contacts from job ads" % (company["company"], found))
            continue
        if not company["company_domain"]:
            log("  %s: %d contacts (no domain, skipped Apollo search)" % (company["company"], found))
            continue
        if found < settings.DECISION_MAKERS_PER_COMPANY:
            try:
                people = providers.apollo_search_people(
                    company["company_domain"], titles, per_page=settings.DECISION_MAKERS_PER_COMPANY * 2)
            except providers.ProviderError as e:
                if not _plan_blocked(e):
                    raise
                log("  Apollo's plan doesn't include the people API; continuing with job-ad contacts only")
                use_apollo = False
                log("  %s: %d contacts from job ads" % (company["company"], found))
                continue
            for p in people:
                if found >= settings.DECISION_MAKERS_PER_COMPANY:
                    break
                if not p.get("has_email"):
                    continue
                person = providers.apollo_enrich_person(person_id=p["id"])
                key = person.get("linkedin_url") or person.get("email")
                if not person or key in seen:
                    continue
                seen.add(key)
                contacts.append(_contact_row(person, company, "Apollo search"))
                found += 1
        log("  %s: %d contacts" % (company["company"], found))
    return contacts


# ---------- Step 2b: free email finding (no paid API) ----------

def fill_free_emails(companies, contacts, log):
    """Learns each company's email format from real emails (job ads, website), finds emails for
    named people, and falls back to the company's hiring inbox when no person has an email."""
    patterns, mail_domains = {}, {}
    targets = [c for c in companies[:settings.MAX_COMPANIES_PER_RUN] if c.get("company_domain")]
    for c in targets:
        domain = c["company_domain"]
        evidence = list(c.get("ad_contact_emails", []))
        site = []
        if settings.CRAWL_COMPANY_WEBSITES:
            site = emailfinder.website_emails(domain)
            credits.USAGE["website_lookups"] += 1
        c["website_emails"] = ", ".join(site[:6])
        # The company's own job ad may use a different mail domain (amsbarging.com ads list @ams-bv.com).
        mail_domain = next((emailfinder.domain_of(e) for e in evidence
                            if emailfinder.domain_of(e) not in emailfinder.FREE_MAIL), domain)
        mail_domains[domain] = mail_domain
        for e in evidence + site:
            p = emailfinder.infer_pattern(e)
            if p and emailfinder.domain_of(e) == mail_domain:
                patterns[domain] = p
                break
        c["email_domain"] = mail_domain
        c["email_format"] = patterns.get(domain, "")
        c["_site_emails"] = site

    found = 0
    for ct in contacts:
        if ct.get("email") or not ct.get("first_name") or not ct.get("last_name"):
            continue
        domain = ct.get("company_domain")
        email, status = emailfinder.find_email(ct["first_name"], ct["last_name"],
                                               mail_domains.get(domain, domain), patterns.get(domain))
        ct["email_status"] = status
        if email:
            ct["email"] = email
            found += 1
    log("  found emails for %d named people (%d companies' formats learned from real emails)" % (found, len(patterns)))

    have_email = {ct.get("company_domain") for ct in contacts if ct.get("email")}
    added = 0
    for c in targets:
        if c["company_domain"] in have_email:
            continue
        site = c.pop("_site_emails", [])
        inbox = next((e for e in site if emailfinder.is_hiring_inbox(e)), None)
        kind = "Company hiring inbox (from website)"
        if not inbox:
            inbox = next((e for e in site if emailfinder.is_generic(e)), None)
            kind = "Company general inbox (from website)"
        if inbox:
            contacts.append(dict(_contact_row({"title": kind, "email": inbox}, c, "company website"),
                                 track="permanent", email_status="from company website"))
            added += 1
    for c in targets:
        c.pop("_site_emails", None)
    log("  added %d company inboxes for companies with no named contact" % added)
    return contacts


def load_people_to_find(path, companies, log):
    """People you found yourself (e.g. via the search links): name + company website -> email."""
    if not os.path.exists(path):
        return []
    by_domain = {c["company_domain"]: c for c in companies if c.get("company_domain")}
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        mapping = _map_columns(reader.fieldnames or [])
        for raw in reader:
            r = {k: (raw.get(col) or "").strip() for k, col in mapping.items()}
            if not r.get("first_name") and r.get("full_name"):
                parts = r["full_name"].split(" ", 1)
                r["first_name"], r["last_name"] = parts[0], parts[1] if len(parts) > 1 else ""
            domain = _domain(r.get("website")) or emailfinder.domain_of(r.get("email", ""))
            company = by_domain.get(domain) or {
                "company": r.get("company", ""), "company_domain": domain, "open_roles_30plus": "",
                "oldest_days_open": "", "countries": "", "sample_roles": ""}
            person = {"first_name": r.get("first_name"), "last_name": r.get("last_name"),
                      "title": r.get("title"), "email": r.get("email"), "linkedin_url": r.get("linkedin_url"),
                      "country": r.get("person_country"), "organization": {"name": r.get("company")}}
            row = _contact_row(person, company, os.path.basename(path))
            row["lead_type"] = "new (added by you)"
            rows.append(row)
    log("  loaded %d people from %s" % (len(rows), os.path.basename(path)))
    return rows


# ---------- Step 3: old prospects ----------

COLUMN_ALIASES = {
    "email": ["email", "email address", "e-mail", "work email", "email id"],
    "first_name": ["first name", "firstname", "first", "given name"],
    "last_name": ["last name", "lastname", "surname", "last", "family name"],
    "full_name": ["name", "full name", "contact name", "contact"],
    "title": ["title", "job title", "designation", "position", "role"],
    "company": ["company", "company name", "organisation", "organization", "account", "client"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "profile url"],
    "person_country": ["country", "location", "country code"],
    "status": ["status", "stage", "lead status", "outcome"],
    "notes": ["notes", "note", "comments", "remarks"],
    "last_contacted": ["last contacted", "last contact", "last activity", "date"],
    "website": ["website", "domain", "company website", "company domain", "url", "web"],
}
DO_NOT_CONTACT = re.compile(r"do not contact|unsubscrib|opted out|opt-out|not interested|bounced|dnc", re.I)


def _map_columns(header):
    mapping = {}
    for col in header:
        norm = col.strip().lower().replace("_", " ")
        for field, aliases in COLUMN_ALIASES.items():
            if norm in aliases and field not in mapping:
                mapping[field] = col
    return mapping


def load_old_prospects(folder, hot_domains, log):
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        log("  no CSV files in %s" % folder)
        return [], []
    kept, removed, seen = [], [], set()
    for path in files:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            mapping = _map_columns(reader.fieldnames or [])
            log("  %s: matched columns %s" % (os.path.basename(path), ", ".join(sorted(mapping))))
            for raw in reader:
                row = {k: (raw.get(col) or "").strip() for k, col in mapping.items()}
                if not row.get("first_name") and row.get("full_name"):
                    parts = row["full_name"].split(" ", 1)
                    row["first_name"] = parts[0]
                    row["last_name"] = parts[1] if len(parts) > 1 else ""
                email = row.get("email", "").lower()
                key = email or row.get("linkedin_url", "").lower()
                reason = ""
                if not key:
                    reason = "no email or LinkedIn"
                elif key in seen:
                    reason = "duplicate"
                elif DO_NOT_CONTACT.search(row.get("status", "") + " " + row.get("notes", "")):
                    reason = "marked do-not-contact / not interested"
                if reason:
                    removed.append(dict(row, removed_reason=reason, source_file=os.path.basename(path)))
                    continue
                seen.add(key)
                domain = email.split("@")[1] if "@" in email else ""
                hot = domain in hot_domains
                kept.append({
                    "first_name": row.get("first_name", ""), "last_name": row.get("last_name", ""),
                    "title": row.get("title", ""), "company": row.get("company", ""),
                    "company_domain": domain, "email": email, "email_status": "",
                    "linkedin_url": row.get("linkedin_url", ""),
                    "person_country": row.get("person_country", ""),
                    "track": track_for_title(row.get("title", "")),
                    "open_roles_30plus": hot_domains[domain]["open_roles_30plus"] if hot else "",
                    "oldest_days_open": hot_domains[domain]["oldest_days_open"] if hot else "",
                    "role_countries": hot_domains[domain]["countries"] if hot else "",
                    "sample_roles": hot_domains[domain]["sample_roles"] if hot else "",
                    "lead_type": "old - HOT (company has 30+ day vacancies)" if hot else "old",
                    "source": os.path.basename(path),
                    "previous_status": row.get("status", ""), "previous_notes": row.get("notes", ""),
                    "last_contacted": row.get("last_contacted", ""),
                })
    kept.sort(key=lambda r: 0 if "HOT" in r["lead_type"] else 1)
    return kept, removed
