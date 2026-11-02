"""Lead engine app. Runs on your computer (Mac or Windows) and opens in your browser."""
import contextlib
import hmac
import csv
import io
import json
import os
import re
import threading
import time
import webbrowser
from datetime import datetime

from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, session, url_for

import credits
import messages
import providers
import run
import settings
import store

HERE = run.HERE
DATA = settings.DATA_ROOT
OUTPUT = os.path.join(DATA, "output")
INPUT = os.path.join(DATA, "input")
OLD_DIR = os.path.join(INPUT, "old_prospects")
PEOPLE_FILE = os.path.join(INPUT, "people_to_find.csv")
PEOPLE_COLS = ["first_name", "last_name", "title", "company", "website", "linkedin_url", "country"]
ENV_FILE = os.path.join(DATA, ".env")
store.restore()  # hosted: bring back results, drafts and settings saved before the last restart
PROFILE_FILE = settings.profile_path()
KEY_NAMES = [("THEIRSTACK_API_KEY", "TheirStack", "Finds job ads open 30+ days"),
             ("APOLLO_API_KEY", "Apollo", "Contact lookup (paid plans only)"),
             ("GEMINI_API_KEY", "Gemini", "Writes the emails and LinkedIn messages"),
             ("GEMINI_API_KEY_BACKUP", "Gemini backup", "Used when the first key hits its daily limit"),
             ("ADZUNA_APP_ID", "Adzuna app ID", "Free backup job source"),
             ("ADZUNA_APP_KEY", "Adzuna app key", "Free backup job source")]
STATUSES = ["Draft", "Sent", "Replied", "Meeting booked", "Not interested", "Skip"]
FILE_LABELS = {
    "01_open_roles_30plus_days.csv": "Open roles (30+ days)",
    "02_target_companies_ranked.csv": "Client companies, ranked",
    "03_new_prospects.csv": "New contacts",
    "04_old_prospects_to_reengage.csv": "Old prospects to re-engage",
    "04b_old_prospects_removed.csv": "Old prospects removed (duplicates, do-not-contact)",
    "05_outreach_messages.csv": "All drafts (email + LinkedIn)",
    "06_email_send_list.csv": "Email send list: confirmed addresses",
    "06b_guessed_emails_check_first.csv": "Email send list: guessed addresses (check first)",
    "07_linkedin_tasks.csv": "LinkedIn to-do list",
    "00_search_playbook.csv": "Manual search strings and job boards",
    "00_credit_usage.csv": "Credit usage for this run",
}

app = Flask(__name__)
# Hosted: set APP_PASSWORD (the team password) and SECRET_KEY in the hosting dashboard.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
app.secret_key = os.environ.get("SECRET_KEY") or "local-only-app"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("SECRET_KEY")),
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30, MAX_CONTENT_LENGTH=10 * 1024 * 1024,
                  PASSWORD_ON=bool(APP_PASSWORD))


@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint in ("login", "static", "health"):
        return None
    if not session.get("user"):
        return redirect(url_for("login", next=request.path))
    return None


@app.after_request
def save_changes(response):
    if request.method == "POST" and response.status_code < 400 and not JOB["running"]:
        store.sync()
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if APP_PASSWORD and hmac.compare_digest(request.form.get("password", ""), APP_PASSWORD):
            session.permanent = True
            session["user"] = request.form.get("name", "").strip()[:40] or "Team member"
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))
        time.sleep(1)
        flash("Wrong password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return {"ok": True}


# ---------- helpers ----------

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def load_env():
    values = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    values[k.strip()] = v.strip()
    return values


def save_env(values):
    lines = ["%s=%s" % (k, values.get(k, "")) for k, _, _ in KEY_NAMES]
    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    for k, _, _ in KEY_NAMES:
        os.environ[k] = values.get(k, "")


def load_profile():
    with open(PROFILE_FILE) as f:
        return json.load(f)


def runs():
    out = []
    if not os.path.isdir(OUTPUT):
        return out
    for name in sorted(os.listdir(OUTPUT), reverse=True):
        path = os.path.join(OUTPUT, name)
        if not os.path.isdir(path) or name.endswith("_sample"):
            continue
        info = {}
        try:
            with open(os.path.join(path, "run_info.json")) as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        try:
            when = datetime.strptime(name[:15], "%Y-%m-%d_%H%M").strftime("%d %b %Y, %H:%M")
        except ValueError:
            when = name
        companies = info.get("companies", len(read_csv(os.path.join(path, "02_target_companies_ranked.csv"))))
        drafts = info.get("drafts", len(read_csv(os.path.join(path, "05_outreach_messages.csv"))))
        countries = info.get("countries") or []
        if info.get("old_only"):
            scope = "Your own lists"
        elif countries and len(countries) < len(settings.all_target_countries()):
            scope = ", ".join(settings.COUNTRY_NAMES.get(c, c) for c in countries[:6]) + (
                " +%d more" % (len(countries) - 6) if len(countries) > 6 else "")
        else:
            scope = "All regions"
        out.append({"id": name, "when": when, "companies": companies, "drafts": drafts, "scope": scope})
    return out


def run_dir(run_id):
    if not re.fullmatch(r"[\w-]+", run_id or ""):
        abort(404)
    path = os.path.join(OUTPUT, run_id)
    if not os.path.isdir(path):
        abort(404)
    return path


_credit_cache = {"at": 0, "value": None}


def credit_panel(force=False):
    if force or time.time() - _credit_cache["at"] > 60:
        providers.load_env(ENV_FILE)
        _credit_cache["value"] = credits.theirstack_balance() if os.environ.get("THEIRSTACK_API_KEY") else None
        _credit_cache["at"] = time.time()
    ts = _credit_cache["value"]
    state = credits.load_state(DATA)
    today = state.get("days", {}).get(datetime.now().strftime("%Y-%m-%d"), {})
    return {"ts": ts, "apollo": state.get("apollo_people_api", "not checked yet"),
            "gemini_today": today.get("gemini_calls", 0), "checks_today": today.get("mailbox_checks", 0),
            "adzuna_on": bool(os.environ.get("ADZUNA_APP_ID")), "adzuna_today": today.get("adzuna_calls", 0)}


EMAIL_BADGES = {
    "verified": ("Verified", "good"), "from job ad": ("From job ad", "good"),
    "from company website": ("Company inbox", "good"),
    "pattern from real email": ("Guessed: company format", "warn"),
    "best guess (common format)": ("Guessed: check first", "warn"),
}


def badge(row):
    if not row.get("email"):
        return ("No email: use LinkedIn", "muted")
    return EMAIL_BADGES.get(row.get("email_status", ""), ("From your list" if row.get("lead_type", "").startswith("old")
                                                          else (row.get("email_status") or "Email"), "good"))


app.jinja_env.globals.update(badge=badge, STATUSES=STATUSES, THRESHOLD=settings.EVAL_THRESHOLD)
app.jinja_env.filters["fromjson"] = lambda text: json.loads(text) if text else []
app.jinja_env.filters["emails"] = lambda text: ", ".join(re.findall(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+", text or ""))


# ---------- background run ----------

JOB = {"running": False, "log": [], "out_dir": None, "error": None, "started": None, "label": "", "by": ""}
_lock = threading.Lock()


# The progress log shows what's happening in plain words, without file names or folders.
HIDE = re.compile(r"^\s*(saved |\(nothing to write|Saving to |=+$| CREDITS - )")
RENAME = [
    (re.compile(r"^1/4 Open roles 30\+ days \((.+)\)"), r"Step 1 of 4: looking for roles open 30+ days (\1)"),
    (re.compile(r"^2/4 Decision-makers.*"), "Step 2 of 4: finding who to contact"),
    (re.compile(r"^2b/4 .*"), "Finding email addresses (job ads, company websites, mailbox check)"),
    (re.compile(r"^3/4 Old prospects.*"), "Step 3 of 4: checking your old prospect lists"),
    (re.compile(r"^4/4 Writing outreach for (\d+) contacts \((.+)\)"), r"Step 4 of 4: writing drafts for \1 contacts"),
    (re.compile(r"^\s*no CSV files in .*"), "  no old prospect lists uploaded"),
    (re.compile(r"^\s*loaded (\d+) people from .*"), r"  \1 people from your list"),
    (re.compile(r"^Done\..*"), "Done. Open the results to review your drafts."),
    (re.compile(r"\(use --include-recent to redo them\)"), "(tick 'Include people already contacted' to redo them)"),
]


def _add_log(text):
    for line in str(text).splitlines():
        if not line.strip() or HIDE.search(line):
            continue
        for pattern, repl in RENAME:
            line = pattern.sub(repl, line)
        JOB["log"].append(line)


class _Writer(io.TextIOBase):
    def write(self, s):
        _add_log(s)
        return len(s)


def _worker(task):
    try:
        with contextlib.redirect_stdout(_Writer()):
            JOB["out_dir"] = task()
    except run.RunError as e:
        JOB["error"] = str(e)
    except Exception as e:  # keep the app alive and show what happened
        JOB["error"] = "Something went wrong: %s" % e
    finally:
        JOB["running"] = False
        _credit_cache["at"] = 0
        try:
            store.sync()
        except Exception as e:
            JOB["log"].append("Couldn't save to the database: %s" % e)


def start_job(opts, label):
    with _lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, log=[], out_dir=None, error=None, started=time.time(), label=label,
                   by=session.get("user", ""))
    providers.load_env(ENV_FILE)
    task = opts if callable(opts) else (lambda: run.execute(opts, sink=_add_log))
    threading.Thread(target=_worker, args=(task,), daemon=True).start()
    return True


# ---------- pages ----------

@app.route("/")
def home():
    profile = load_profile()
    env = load_env()
    setup_missing = []
    if "YOUR FIRM" in profile.get("company_name", "") or not profile.get("company_name"):
        setup_missing.append("your company details")
    if not (env.get("THEIRSTACK_API_KEY") or os.environ.get("THEIRSTACK_API_KEY")):
        setup_missing.append("a TheirStack key")
    return render_template("home.html", credits=credit_panel(), regions=settings.REGIONS,
                           names=settings.COUNTRY_NAMES, adzuna=settings.ADZUNA_COUNTRIES,
                           runs=runs()[:8], job=JOB, setup_missing=setup_missing,
                           people_waiting=len(read_csv(PEOPLE_FILE)),
                           old_files=len([f for f in os.listdir(OLD_DIR) if f.endswith(".csv")]) if os.path.isdir(OLD_DIR) else 0)


@app.route("/credits/refresh")
def refresh_credits():
    credit_panel(force=True)
    return redirect(url_for("home"))


@app.route("/run", methods=["POST"])
def start_run():
    countries = request.form.getlist("countries")
    if not countries:
        flash("Pick at least one country.")
        return redirect(url_for("home"))
    opts = run.default_options(
        countries=",".join(countries),
        max_jobs=max(1, min(500, int(request.form.get("max_jobs") or 25))),
        max_companies=max(1, min(100, int(request.form.get("max_companies") or 15))),
        source=request.form.get("source", "auto"),
        no_ai=request.form.get("ai") != "on",
        include_recent=request.form.get("include_recent") == "on")
    if not start_job(opts, "Finding clients in %d countries" % len(countries)):
        flash("A search is already running.")
    return redirect(url_for("job_page"))


@app.route("/run-lists", methods=["POST"])
def run_lists():
    opts = run.default_options(old_only=True, no_ai=request.form.get("ai") == "off")
    if not start_job(opts, "Finding emails and writing drafts for your lists"):
        flash("A search is already running.")
    return redirect(url_for("job_page"))


@app.route("/job")
def job_page():
    return render_template("job.html", job=JOB)


@app.route("/job/status")
def job_status():
    since = int(request.args.get("since", 0))
    return {"running": JOB["running"], "lines": JOB["log"][since:], "total": len(JOB["log"]),
            "error": JOB["error"], "run": os.path.basename(JOB["out_dir"]) if JOB["out_dir"] else None,
            "elapsed": int(time.time() - JOB["started"]) if JOB["started"] else 0}


@app.route("/results")
@app.route("/results/<run_id>")
def results(run_id=None):
    all_runs = runs()
    if not run_id:
        if not all_runs:
            flash("No results yet. Run a search first.")
            return redirect(url_for("home"))
        run_id = all_runs[0]["id"]
    path = run_dir(run_id)
    tab = request.args.get("tab", "drafts")
    companies = read_csv(os.path.join(path, "02_target_companies_ranked.csv"))
    drafts = read_csv(os.path.join(path, "05_outreach_messages.csv"))
    for i, d in enumerate(drafts):
        d["_i"] = i
        if d.get("review_status", "").upper().startswith("DRAFT"):
            d["review_status"] = "Draft"
    roles = read_csv(os.path.join(path, "01_open_roles_30plus_days.csv"))
    files = [(f, FILE_LABELS.get(f, f)) for f in sorted(os.listdir(path)) if f.endswith(".csv")]
    info = next((r for r in all_runs if r["id"] == run_id), {"when": run_id, "scope": ""})
    return render_template("results.html", run_id=run_id, info=info, runs=all_runs, tab=tab,
                           companies=companies, drafts=drafts, roles=roles, files=files)


@app.route("/results/<run_id>/draft/<int:i>", methods=["POST"])
def save_draft(run_id, i):
    path = run_dir(run_id)
    file = os.path.join(path, "05_outreach_messages.csv")
    rows = read_csv(file)
    if i >= len(rows):
        abort(404)
    r = rows[i]
    for field in ("email", "email_subject", "email_2_subject", "email_3_subject", "linkedin_connection_note",
                  "linkedin_followup_1", "linkedin_followup_2", "call_opener", "call_bridge"):
        if field in request.form:
            r[field] = request.form[field].strip()
    for field in ("email_body", "email_2_body", "email_3_body", "call_objections"):
        if field in request.form:
            r[field] = request.form[field].replace("\r\n", "\n").strip()
    if request.form.get("review_status") in STATUSES:
        r["review_status"] = request.form["review_status"]
    r["updated_by"] = session.get("user", "")
    r["updated_at"] = datetime.now().strftime("%d %b %H:%M")
    r["linkedin_note_chars"] = str(len(r.get("linkedin_connection_note", "")))
    write_rows(file, rows)
    with contextlib.redirect_stdout(io.StringIO()):
        run._sink[0] = lambda m: None
        run.export_send_files(path, rows)
    if request.headers.get("X-Requested-With") == "fetch":
        return {"ok": True}
    flash("Saved.")
    return redirect(url_for("results", run_id=run_id, tab="drafts") + "#d%d" % i)


@app.route("/results/<run_id>/redraft", methods=["POST"])
def redraft(run_id):
    path = run_dir(run_id)
    if not start_job(lambda: run.redraft(path, sink=_add_log), "Re-writing drafts with the latest settings"):
        flash("Something is already running.")
    return redirect(url_for("job_page"))


@app.route("/results/<run_id>/draft/<int:i>/reply", methods=["POST"])
def reply_helper(run_id, i):
    path = run_dir(run_id)
    file = os.path.join(path, "05_outreach_messages.csv")
    rows = read_csv(file)
    if i >= len(rows):
        abort(404)
    text = request.form.get("reply", "").strip()
    if not text:
        return {"error": "Paste their reply first."}, 400
    providers.load_env(ENV_FILE)
    try:
        out = messages.handle_reply(rows[i], text, load_profile())
    except providers.ProviderError as e:
        return {"error": "The AI couldn't answer right now: %s" % e}, 502
    r = rows[i]
    r["last_reply"] = text
    r["reply_type"] = out.get("classification", "")
    r["reply_suggestion"] = out.get("suggested_reply", "")
    r["reply_next_action"] = out.get("next_action", "")
    r["discovery_questions"] = "\n".join(out.get("discovery_questions") or [])
    if r.get("review_status", "").upper().startswith("DRAFT") or r.get("review_status") in ("Draft", "Sent"):
        r["review_status"] = "Replied"
    r["updated_by"] = session.get("user", "")
    r["updated_at"] = datetime.now().strftime("%d %b %H:%M")
    write_rows(file, rows)
    with contextlib.redirect_stdout(io.StringIO()):
        run._sink[0] = lambda m: None
        run.export_send_files(path, rows)
    return out


@app.route("/download/<run_id>/<name>")
def download(run_id, name):
    path = run_dir(run_id)
    if name not in os.listdir(path) or not name.endswith(".csv"):
        abort(404)
    return send_from_directory(path, name, as_attachment=True)


@app.route("/people", methods=["GET", "POST"])
def people():
    os.makedirs(OLD_DIR, exist_ok=True)
    existing = read_csv(PEOPLE_FILE)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            row = {c: request.form.get(c, "").strip() for c in PEOPLE_COLS}
            if not (row["first_name"] and row["last_name"] and (row["website"] or row["company"])):
                flash("Add at least a first name, last name and the company website.")
            else:
                existing.append(row)
                write_rows(PEOPLE_FILE, [{c: r.get(c, "") for c in PEOPLE_COLS} for r in existing])
                flash("Added %s %s." % (row["first_name"], row["last_name"]))
        elif action == "remove":
            idx = int(request.form.get("i", -1))
            if 0 <= idx < len(existing):
                existing.pop(idx)
                write_rows(PEOPLE_FILE, existing) if existing else os.remove(PEOPLE_FILE)
        elif action == "clear":
            if os.path.exists(PEOPLE_FILE):
                os.remove(PEOPLE_FILE)
            flash("List cleared.")
        elif action == "upload":
            f = request.files.get("file")
            if not f or not f.filename.lower().endswith(".csv"):
                flash("Choose a .csv file (in Excel: File > Save As > CSV).")
            else:
                name = re.sub(r"[^\w.-]", "_", os.path.basename(f.filename))
                f.save(os.path.join(OLD_DIR, name))
                flash("Uploaded %s." % name)
        elif action == "delete_file":
            name = os.path.basename(request.form.get("name", ""))
            p = os.path.join(OLD_DIR, name)
            if name.endswith(".csv") and os.path.exists(p):
                os.remove(p)
                flash("Removed %s." % name)
        return redirect(url_for("people"))
    files = []
    for name in sorted(os.listdir(OLD_DIR)):
        if name.endswith(".csv"):
            files.append({"name": name, "rows": len(read_csv(os.path.join(OLD_DIR, name)))})
    prefill = {"company": request.args.get("company", ""), "website": request.args.get("website", "")}
    return render_template("people.html", people=existing, files=files, prefill=prefill, job=JOB)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    profile = load_profile()
    env = load_env()
    if request.method == "POST":
        for k in profile:
            if k in request.form:
                v = request.form[k].strip()
                if k == "proof_points":
                    profile[k] = [p.strip() for p in v.splitlines() if p.strip()]
                elif k == "deputation_minimum_months":
                    profile[k] = int(v or 6)
                else:
                    profile[k] = v
        with open(PROFILE_FILE, "w") as f:
            json.dump(profile, f, indent=2)
        for k, _, _ in KEY_NAMES:
            v = request.form.get("key_" + k, "").strip()
            if v == "__clear__":
                env[k] = ""
            elif v:
                env[k] = v
        save_env(env)
        _credit_cache["at"] = 0
        flash("Settings saved.")
        return redirect(url_for("settings_page"))
    keys = []
    for k, label, help_ in KEY_NAMES:
        value = env.get(k) or os.environ.get(k, "")
        keys.append({"name": k, "label": label, "help": help_, "set": bool(value),
                     "hint": ("…" + value[-4:]) if value else ""})
    return render_template("settings.html", profile=profile, keys=keys)


@app.route("/guide")
def guide():
    return render_template("guide.html")


os.makedirs(OUTPUT, exist_ok=True)
os.makedirs(OLD_DIR, exist_ok=True)
providers.load_env(ENV_FILE)


def main():
    port = int(os.environ.get("PORT", 5055))
    if os.environ.get("OPEN_BROWSER", "1") == "1":
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:%d" % port)).start()
    print("Lead Engine is running at http://127.0.0.1:%d  (keep this window open; close it to stop)" % port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
