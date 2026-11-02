"""Oil & Gas lead engine. Finds prospects, cleans old ones, writes outreach, saves CSVs.

Usage:
    python3 run.py                 # full run with your API keys
    python3 run.py --old-only      # only re-engage your old prospects (no paid APIs except Gemini)
    python3 run.py --sample        # test run on built-in sample data, no keys needed
    python3 run.py --no-ai         # use the built-in templates instead of Gemini
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

import credits
import history
import messages
import pipeline
import playbook
import providers
import settings

HERE = os.path.dirname(os.path.abspath(__file__))
# Where results, history and your lists are kept. Hosted, this points at a persistent disk.
DATA = settings.DATA_ROOT
GUESSED_STATUSES = ("pattern from real email", "best guess (common format)")


class RunError(Exception):
    pass


_sink = [lambda msg: print(msg, flush=True)]


def log(msg):
    _sink[0](msg)


DEFAULTS = {"JOBS_PER_RUN": settings.JOBS_PER_RUN, "MAX_COMPANIES_PER_RUN": settings.MAX_COMPANIES_PER_RUN}


def default_options(**overrides):
    opts = argparse.Namespace(sample=False, old_only=False, no_ai=False, max_jobs=None, max_companies=None,
                              include_recent=False, credits=False, countries=None, region=None,
                              source="auto", list_countries=False)
    for k, v in overrides.items():
        setattr(opts, k, v)
    return opts


def write_csv(path, rows, columns=None):
    if not rows:
        log("  (nothing to write for %s)" % os.path.basename(path))
        return
    if not columns:
        columns = []
        for r in rows:
            columns += [k for k in r if not k.startswith("_") and k not in columns]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ", ".join(v) if isinstance(v, list) else v for k, v in r.items()})
    log("  saved %s (%d rows)" % (os.path.relpath(path, DATA), len(rows)))


def load_sample():
    with open(os.path.join(HERE, "sample_data", "sample_roles.json")) as f:
        roles = json.load(f)
    for r in roles:
        r["days_open"] = pipeline._days_open(r["date_posted"])
        r["region"] = pipeline.settings.region_for(r["country_code"])
        r["hiring_team"] = ""
        r["_hiring_team_raw"] = []
    with open(os.path.join(HERE, "sample_data", "sample_contacts.json")) as f:
        people = json.load(f)
    return roles, people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--old-only", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--max-jobs", type=int, help="job ads to pull (default %d)" % settings.JOBS_PER_RUN)
    ap.add_argument("--max-companies", type=int, help="companies to find contacts at (default %d)" % settings.MAX_COMPANIES_PER_RUN)
    ap.add_argument("--include-recent", action="store_true", help="also re-draft people drafted in the last %d days" % settings.RECONTACT_AFTER_DAYS)
    ap.add_argument("--credits", action="store_true", help="just show credit usage and exit")
    ap.add_argument("--countries", help="only these countries, e.g. NG,AO,GB (see --list-countries)")
    ap.add_argument("--region", action="append", help="only this region, e.g. Africa (repeat for more)")
    ap.add_argument("--source", choices=["auto", "theirstack", "adzuna", "both"], default="auto",
                    help="job source: auto = TheirStack, switching to Adzuna when credits run out")
    ap.add_argument("--list-countries", action="store_true", help="show country codes by region and exit")
    ap.add_argument("--redraft", metavar="RUN", help="re-write the drafts of an earlier search, e.g. 2026-11-02_1729")
    args = ap.parse_args()
    if args.redraft:
        path = os.path.join(DATA, "output", os.path.basename(args.redraft))
        if not os.path.isdir(path):
            log("No search called %s in output/" % args.redraft)
            sys.exit(1)
        redraft(path, use_ai=not args.no_ai)
        return
    try:
        execute(args)
    except RunError as e:
        log(str(e))
        sys.exit(1)


def execute(args, sink=None):
    """Runs the whole engine. Returns the output folder (or None). Used by run.py and the app."""
    if sink:
        _sink[0] = sink
    for k, v in DEFAULTS.items():
        setattr(settings, k, v)
    pipeline.APOLLO_BLOCKED = None
    for k in credits.USAGE:
        credits.USAGE[k] = 0
    if args.list_countries:
        for region, codes in settings.REGIONS.items():
            log("%s:" % region)
            for c in codes:
                log("  %s  %-20s %s" % (c, settings.COUNTRY_NAMES.get(c, ""),
                                        "TheirStack + Adzuna" if c in settings.ADZUNA_COUNTRIES else "TheirStack"))
        return None
    try:
        countries = settings.pick_countries((args.countries or "").split(",") if args.countries else None, args.region)
    except ValueError as e:
        raise RunError(str(e))
    if args.max_jobs:
        settings.JOBS_PER_RUN = args.max_jobs
    if args.max_companies:
        settings.MAX_COMPANIES_PER_RUN = args.max_companies

    providers.load_env(os.path.join(DATA, ".env"))
    with open(settings.profile_path()) as f:
        profile = json.load(f)
    if "." in profile.get("website", "") and "yourfirm" not in profile["website"]:
        settings.SMTP_HELO_DOMAIN = pipeline._domain(profile["website"])

    if args.credits:
        credits.report(DATA, "current balance")
        return None

    skip_job_search = False
    use_theirstack = args.source in ("auto", "theirstack", "both")
    use_adzuna = args.source in ("adzuna", "both")
    if not args.sample and not args.old_only and use_theirstack:
        ts = credits.theirstack_balance()
        credits.report(DATA, "before this run", ts)
        if ts and ts["left"] == 0:
            use_theirstack = False
            if args.source == "auto" and os.environ.get("ADZUNA_APP_ID"):
                log("TheirStack credits are used up until %s: using Adzuna (free) instead.\n" % ts["renews"])
                use_adzuna = True
            elif not use_adzuna:
                log("TheirStack credits are used up until %s: skipping the job search this run.\n" % ts["renews"])
                skip_job_search = True
        elif ts and ts["left"] < settings.JOBS_PER_RUN:
            log("Only %d TheirStack credits left: pulling %d job ads instead of %d.\n"
                % (ts["left"], ts["left"], settings.JOBS_PER_RUN))
            settings.JOBS_PER_RUN = ts["left"]

    out_dir = os.path.join(DATA, "output", datetime.now().strftime("%Y-%m-%d_%H%M") + ("_sample" if args.sample else ""))
    os.makedirs(out_dir, exist_ok=True)
    log("Saving to %s\n" % os.path.relpath(out_dir, DATA))

    write_csv(os.path.join(out_dir, "00_search_playbook.csv"), playbook.rows())

    roles, companies, new_contacts = [], [], []
    try:
        if args.sample:
            log("1/4 Open roles 30+ days (sample data)")
            roles, sample_people = load_sample()
            companies = pipeline.summarise_companies(roles)
            by_domain = {c["company_domain"]: c for c in companies}
            new_contacts = [pipeline._contact_row(p, by_domain[p["company_domain"]], "sample")
                            for p in sample_people if p["company_domain"] in by_domain]
        elif not args.old_only and not skip_job_search:
            log("Countries: %s\n" % ", ".join(countries))
            if use_theirstack:
                log("1/4 Open roles 30+ days (TheirStack)")
                roles += pipeline.find_open_roles(log, countries)
            if use_adzuna:
                log("1/4 Open roles 30+ days (Adzuna, free)")
                roles += pipeline.find_open_roles_adzuna(log, countries)
            companies = pipeline.summarise_companies(roles)
            log("  %d roles across %d companies" % (len(roles), len(companies)))
            if any(not c["company_domain"] for c in companies):
                pipeline.resolve_missing_domains(companies, log)
            use_apollo = bool(os.environ.get("APOLLO_API_KEY", "").strip())
            if use_apollo:
                log("\n2/4 Decision-makers (Apollo)")
            else:
                log("\n2/4 Decision-makers (no Apollo key: hiring contacts from job ads only, LinkedIn but no email)")
            new_contacts = pipeline.find_decision_makers(companies, log, use_apollo)
        if not args.sample:
            new_contacts += pipeline.load_people_to_find(
                os.path.join(DATA, "input", "people_to_find.csv"), companies, log)
            log("\n2b/4 Free email finder (company email formats, website inboxes, mailbox check)")
            new_contacts = pipeline.fill_free_emails(companies, new_contacts, log)
    except providers.ProviderError as e:
        raise RunError("Stopped: %s" % e)

    write_csv(os.path.join(out_dir, "01_open_roles_30plus_days.csv"), roles)
    write_csv(os.path.join(out_dir, "02_target_companies_ranked.csv"), companies)
    write_csv(os.path.join(out_dir, "03_new_prospects.csv"), new_contacts)

    log("\n3/4 Old prospects (input/old_prospects/*.csv)")
    old_folder = os.path.join(HERE, "sample_data", "old_prospects") if args.sample else os.path.join(DATA, "input", "old_prospects")
    hot = {c["company_domain"]: c for c in companies if c["company_domain"]}
    old_contacts, removed = pipeline.load_old_prospects(old_folder, hot, log)
    write_csv(os.path.join(out_dir, "04_old_prospects_to_reengage.csv"), old_contacts)
    write_csv(os.path.join(out_dir, "04b_old_prospects_removed.csv"), removed)

    # Never message someone twice in one run, or again within RECONTACT_AFTER_DAYS.
    history_path = os.path.join(DATA, "data", "sample_history.csv" if args.sample else "outreach_history.csv")
    past = history.load(history_path)
    seen, all_contacts, skipped = set(), [], 0
    for c in new_contacts + old_contacts:
        key = history.contact_key(c)
        if not key or key in seen:
            continue
        seen.add(key)
        if not args.include_recent and history.recently_drafted(past, c, settings.RECONTACT_AFTER_DAYS):
            skipped += 1
            continue
        all_contacts.append(c)
    if skipped:
        log("\n  skipped %d people already drafted in the last %d days (use --include-recent to redo them)"
            % (skipped, settings.RECONTACT_AFTER_DAYS))

    use_ai = not args.no_ai and bool(os.environ.get("GEMINI_API_KEY"))
    log("\n4/4 Writing outreach for %d contacts (%s)" % (len(all_contacts), "Gemini" if use_ai else "templates"))
    rows = messages.build_messages(all_contacts, profile, use_ai, log)
    write_csv(os.path.join(out_dir, "05_outreach_messages.csv"), rows)
    export_send_files(out_dir, rows)

    history.record(history_path, rows)
    if not args.sample:
        credits.record_run(DATA, apollo_blocked=pipeline.APOLLO_BLOCKED)
        write_csv(os.path.join(out_dir, "00_credit_usage.csv"), credits.report(DATA, "after this run"))
    with open(os.path.join(out_dir, "run_info.json"), "w") as f:
        json.dump({"countries": [] if args.old_only else countries, "old_only": bool(args.old_only),
                   "sample": bool(args.sample), "companies": len(companies), "drafts": len(rows),
                   "finished": datetime.now().isoformat(timespec="minutes")}, f)
    log("\nDone. Review 05_outreach_messages.csv, then import 06 into your mail tool and work through 07 on LinkedIn.")
    return out_dir


def redraft(out_dir, use_ai=True, sink=None):
    """Re-writes the drafts of an earlier search with the current settings and method, without a new
    job search. Drafts already marked Sent, Replied etc. are left exactly as they are."""
    if sink:
        _sink[0] = sink
    for k in credits.USAGE:
        credits.USAGE[k] = 0
    providers.load_env(os.path.join(DATA, ".env"))
    with open(settings.profile_path()) as f:
        profile = json.load(f)

    def read(name):
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            return []
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    old_rows = read("05_outreach_messages.csv")
    keep = {history.contact_key(r): r for r in old_rows
            if r.get("review_status", "").lower() not in ("", "draft", "draft - review before sending")}
    contacts, seen = [], set()
    for c in read("03_new_prospects.csv") + read("04_old_prospects_to_reengage.csv"):
        key = history.contact_key(c)
        if key and key not in seen and key not in keep:
            seen.add(key)
            c.setdefault("track", pipeline.track_for_title(c.get("title", "")))
            contacts.append(c)
    use_ai = use_ai and bool(os.environ.get("GEMINI_API_KEY"))
    log("Re-writing drafts for %d contacts (%d already sent or in progress are kept)" % (len(contacts), len(keep)))
    rows = messages.build_messages(contacts, profile, use_ai, log)
    rows = list(keep.values()) + rows
    write_csv(os.path.join(out_dir, "05_outreach_messages.csv"), rows)
    export_send_files(out_dir, rows)
    credits.record_run(DATA)
    log("\nDone. Open the results to review your drafts.")
    return out_dir


def export_send_files(out_dir, rows):
    """06/06b/07 come from the drafts, so they're rebuilt whenever a draft is edited."""
    # Ready to import into Gmail mail merge, Instantly, Lemlist, etc.
    # Guessed addresses go in their own file: sending lots that bounce hurts your domain.
    send_cols = ["email", "first_name", "last_name", "company", "title", "pitch", "eval_score",
                 "email_subject", "email_body", "email_2_subject", "email_2_body", "email_3_subject", "email_3_body",
                 "email_status"]
    active = [r for r in rows if r.get("review_status", "").lower() not in ("sent", "not interested", "skip")]
    emailable = [r for r in active if r["email"] and r["email_status"] not in ("invalid", "unavailable", "bounced")]
    guessed = [r for r in emailable if r["email_status"] in GUESSED_STATUSES]
    for name, data in (("06_email_send_list.csv", [r for r in emailable if r not in guessed]),
                       ("06b_guessed_emails_check_first.csv", guessed)):
        path = os.path.join(out_dir, name)
        if not data and os.path.exists(path):
            os.remove(path)
        write_csv(path, data, send_cols)
    linkedin = [dict(r, step_1="Send connection request with note",
                     step_2="Day after they accept: send follow-up 1",
                     step_3="5 days later, if no reply: send follow-up 2")
                for r in active if r["linkedin_url"]]
    write_csv(os.path.join(out_dir, "07_linkedin_tasks.csv"), linkedin,
              ["first_name", "last_name", "company", "title", "linkedin_url", "step_1", "linkedin_connection_note",
               "step_2", "linkedin_followup_1", "step_3", "linkedin_followup_2"])


if __name__ == "__main__":
    main()
