"""Step 4: research pack -> outreach sequence -> separate eval, following the Art of Selling method
(Prof. Rishabh Ladha): the goal of outreach is one thing, a meeting. Write about their problem, not
our product; only verified facts as fact; one low ask; every touch adds something new; a separate
pass grades the drafts and a human approves before anything is sent."""
import json
import re

import providers
import settings

EMAIL_WORD_LIMIT = 120
FOLLOWUP_WORD_LIMIT = 90
LINKEDIN_NOTE_LIMIT = 300
LINKEDIN_DM_LIMIT = 300

GDPR_COUNTRY_NAMES = {
    "united kingdom", "uk", "england", "scotland", "norway", "netherlands", "denmark",
    "germany", "france", "italy", "romania", "poland", "ireland", "spain", "portugal",
    "cyprus", "greece", "belgium", "sweden", "finland", "austria", "switzerland", "iceland",
}


def is_gdpr(contact):
    c = (contact.get("person_country") or "").strip()
    if c.upper() in settings.GDPR_COUNTRIES or c.lower() in GDPR_COUNTRY_NAMES:
        return True
    countries = [x.strip() for x in (contact.get("role_countries") or "").split(",")]
    return any(x in settings.GDPR_COUNTRIES for x in countries)


def word_count(text):
    return len(re.findall(r"\b[\w'’/&-]+\b", text or ""))


def signature(profile):
    return "%s\n%s, %s\n%s | %s" % (
        profile["sender_name"], profile["sender_title"], profile["company_name"],
        profile["website"], profile["sender_phone"])


def footer(profile, gdpr):
    lines = []
    if gdpr:
        lines.append("You're receiving this because your role involves hiring for energy projects "
                     "that %s recruits for." % profile["company_name"])
    lines.append(profile["unsubscribe_text"])
    lines.append(profile["postal_address"])
    return "\n".join(lines)


def _possessive(name):
    return name + ("'" if name.endswith("s") else "'s")


def _country(code):
    return settings.COUNTRY_NAMES.get(code, code)


# ---------- Personalization pack: the clean context window ----------

# Persona cards: hired for / measured on / fired for. Hypotheses (Assertions) until real calls
# confirm them, so the writer may only use them as questions.
PERSONAS = {
    "permanent": {
        "persona": "HR / Talent Acquisition / Operations leader at an energy company",
        "hired_for": "keeping projects and operations staffed with qualified, compliant people",
        "measured_on": "time-to-fill, cost-per-hire, offer acceptance, retention, local-content quotas",
        "fired_for": "a project slipping because a critical seat stayed empty; agency spend overruns",
        "top_pains": ["niche roles that job boards don't fill", "agency fees of 15-25% eating the budget",
                      "hiring managers chasing them for candidates"],
    },
    "deputation": {
        "persona": "Project / Construction / Commissioning / Operations manager",
        "hired_for": "delivering the project on schedule, safely and on budget",
        "measured_on": "schedule milestones (mechanical completion, start-up), HSE record, OPEX/CAPEX",
        "fired_for": "missed milestones, liquidated damages, safety incidents from stretched crews",
        "top_pains": ["work fronts waiting on people", "overtime and fatigue on the existing crew",
                      "permanent headcount approvals that take longer than the project allows"],
    },
}

# Industry shifts by signal. Assertions: plausible, not verified for this account -> question form only.
def _industry_shifts(contact, signals):
    shifts = []
    titles = " ".join(s.get("role", "") for s in signals).lower()
    countries = {s.get("country") for s in signals} | {x.strip() for x in (contact.get("role_countries") or "").split(",")}
    if re.search(r"commission|start-?up|completion", titles):
        shifts.append("Commissioning and start-up roles sit on the critical path late in a project; an open seat "
                      "there can hold up handover.")
    if re.search(r"drill|rig|toolpusher|well", titles):
        shifts.append("Experienced drilling supervisors are mobile and often on rotation elsewhere, so ads "
                      "alone rarely fill these seats quickly.")
    if re.search(r"hse|safety", titles):
        shifts.append("HSE roles are often a condition of operating, so a gap carries compliance risk, not just workload.")
    if countries & {"NG", "AO", "GA", "CG", "GQ", "CM", "MZ", "TZ", "GH", "SN", "UG", "KE", "DZ", "LY", "EG"}:
        shifts.append("National-content expectations in many African producing countries narrow the candidate "
                      "pool to nationals or require handover plans.")
    if not shifts:
        shifts.append("Energy companies are competing for the same experienced project people across "
                      "oil & gas and energy-transition work.")
    return shifts


def build_pack(contact, profile):
    """Everything the writer may use, each claim tagged Verified (source + date) or Assertion."""
    try:
        signals = json.loads(contact.get("signals") or "[]")
    except ValueError:
        signals = []
    if not signals and contact.get("sample_roles"):
        for part in contact["sample_roles"].split(" | "):
            m = re.match(r"(.+?) \((\w*), (\d+) days\)", part)
            if m:
                signals.append({"role": m.group(1), "country": m.group(2), "days_open": m.group(3),
                                "date_posted": "", "url": ""})
    claims = []
    for s in signals:
        src = "job ad" + (" " + s["url"] if s.get("url") else "") + (", posted " + s["date_posted"] if s.get("date_posted") else "")
        claims.append({"claim": "%s is advertising a %s role in %s, open %s days"
                       % (contact.get("company"), s.get("role"), _country(s.get("country", "")), s.get("days_open")),
                       "status": "Verified", "source": src})
        if s.get("snippet"):
            claims.append({"claim": "The ad says: \"%s\"" % s["snippet"][:300], "status": "Verified", "source": src})
    if contact.get("industry"):
        claims.append({"claim": "%s is in %s" % (contact.get("company"), contact["industry"]),
                       "status": "Verified", "source": "company profile on the job platform"})
    if contact.get("previous_notes") or contact.get("previous_status"):
        claims.append({"claim": "Our past notes: %s %s" % (contact.get("previous_status", ""), contact.get("previous_notes", "")),
                       "status": "Verified", "source": "your CRM export (internal: do not quote back verbatim)"})
    persona = PERSONAS[contact.get("track", "permanent")]
    shifts = _industry_shifts(contact, signals)
    for sh in shifts:
        claims.append({"claim": sh, "status": "Assertion", "source": "industry pattern; use only as a question"})
    proof = [p for p in profile.get("proof_points") or [] if p.strip()]
    verified = sum(1 for c in claims if c["status"] == "Verified")
    has_signal = bool(signals)
    if has_signal:
        icp = ("Yes", "Energy company with %d role(s) advertised 30+ days: a verified hiring signal." % len(signals))
    elif contact.get("lead_type", "").startswith("old"):
        icp = ("Unsure", "Past contact with no current hiring signal; re-engage gently, ask about upcoming projects.")
    else:
        icp = ("Unsure", "No verified hiring signal yet; open with a question about their upcoming projects.")
    person_signal = "none verified (we don't read LinkedIn posts); fall back to the company signal"
    hooks = []
    if signals:
        top = max(signals, key=lambda s: int(s.get("days_open") or 0))
        hooks.append("Their %s role in %s has been open %s days" % (top.get("role"), _country(top.get("country", "")), top.get("days_open")))
    hooks += ["Second-order cost of the gap: " + persona["fired_for"], shifts[0]]
    return {
        "us": "%s: oil & gas recruitment across %s, %s. Permanent: %s (market: %s). Contract deputation: %s, minimum %s months."
              % (profile["company_name"], profile["regions_served"], profile["disciplines"], profile["permanent_fee"],
                 profile["typical_market_fee"], profile["deputation_billing"], profile["deputation_minimum_months"]),
        "icp_fit": icp[0], "icp_reason": icp[1],
        "company": contact.get("company", ""),
        "greeting": "Hi %s," % (contact.get("first_name") or ("%s team" % contact.get("company") if contact.get("company") else "there")),
        "sender": profile.get("sender_name", ""), "sender_company": profile.get("company_name", ""),
        "person": {"name": ("%s %s" % (contact.get("first_name", ""), contact.get("last_name", ""))).strip() or "unknown (company inbox)",
                   "title": contact.get("title", ""), "personal_signal": person_signal},
        "persona": persona,
        "claims": claims,
        "best_hooks": hooks[:3],
        "likely_objections": [
            "We already use agencies / have a PSL (Proof: why you?)",
            "No budget / headcount frozen (Problem: is the gap costing enough?)",
            "Send me some info (Ask: too big or unclear)",
        ],
        "proof_we_can_cite": proof or ["NONE: do not claim placements, clients, speed or results"],
        "guarantee": profile.get("replacement_guarantee") or "NONE: never say risk-free or guaranteed",
        "do_not_use": ["anything not in claims/proof", "flattery", "quotes the person never said",
                       "stats or numbers not in claims", "the CRM note verbatim"],
        "verification_ratio": "%d verified / %d total claims" % (verified, len(claims)),
    }


def pack_text(pack):
    lines = ["PERSON: %s, %s at %s" % (pack["person"]["name"], pack["person"]["title"] or "role unknown", pack["company"]),
             "GREETING TO USE (exactly): " + pack["greeting"],
             "SENDER (for the call script): %s, %s" % (pack["sender"], pack["sender_company"]),
             "Personal signal: " + pack["person"]["personal_signal"],
             "ICP FIT: %s - %s" % (pack["icp_fit"], pack["icp_reason"]),
             "Verification: " + pack["verification_ratio"], "", "Claims:"]
    for c in pack["claims"]:
        lines.append("- [%s] %s (%s)" % (c["status"], c["claim"], c["source"]))
    p = pack["persona"]
    lines += ["", "Persona (hypothesis): %s. Hired for %s; measured on %s; fired for %s."
              % (p["persona"], p["hired_for"], p["measured_on"], p["fired_for"]),
              "Best hooks: " + " | ".join(pack["best_hooks"]),
              "Proof we can cite: " + "; ".join(pack["proof_we_can_cite"])]
    return "\n".join(lines)


# ---------- Writing ----------

WRITE_PROMPT = """You write one-to-one B2B outreach for an oil & gas recruitment firm, using the Art of Selling
method. The ONLY goal is a short meeting or a small next step, never to sell in the message.
We want this company as a CLIENT (they pay us to fill roles). Never pitch them a job or ask for a CV.

PERSONALIZATION PACK (the only facts you may use):
{pack}

PITCH TRACK: {track}
- permanent: an HR/Talent/Operations leader. Problem = the cost of the open vacancy. Our offer, in ONE
  short line, never the hero: {fee} instead of the usual {market}.
- deputation: a Project/Operations manager. Problem = the schedule waiting on people. Our offer, in ONE
  short line, never the hero: {billing} for contract roles of minimum {months} months, keeping OPEX fluid.

RULES (non-negotiable):
- Only [Verified] claims may be stated as fact. [Assertion] claims may ONLY appear as a question or
  hypothesis ("Is that what you're seeing?"). Never invent numbers, clients, placements, speed, quotes.
- About THEM, not us. Insight = state the pain, then agitate it (the second-order effect). No product-first openings.
- No warm-up filler: no "Hope you're well", "I'm reaching out", "I wanted to", "just checking in".
- Peer-to-peer, short sentences, no sales language, no emojis, no exclamation marks.
- Exactly ONE low, specific ask per message (e.g. "Worth 15 minutes on Thursday?" or "Want me to send
  three anonymised profiles for the {role_hint} seat?"). Never "let me know".
- Start every email and LinkedIn message with the exact GREETING TO USE from the pack. Never write
  placeholders like <first name>, [Name] or [Company]; use the SENDER from the pack in the call script.
- The call script follows the same evidence rules: [Assertion] claims only as questions.
- No signature or sign-off (added later). Separate short paragraphs with a blank line.
- Every touch adds NEW information or angle; never repeat the previous email.
{fix_block}
Write this sequence:
1. email_1 (Day 1, evidence-led): open with the verified job-ad signal; pain + agitate; one line of offer; one ask. Under {limit} words.
2. email_2 (Day 3, insight-led, new angle): an industry/persona hypothesis as a question, plus the OTHER way we can help
   (if track is permanent mention contract deputation as an option, and vice versa); smaller ask. Under {flimit} words.
3. email_3 (Day 8, last touch): smallest ask, e.g. "Is this something for you, or should I speak to someone else?". Under 60 words.
4. linkedin_connection_note: max {note} characters, references the specific signal, no pitch.
5. linkedin_followup_1 (after they accept): max {dm} characters, asks which project gaps are hardest to fill right now.
6. linkedin_followup_2 (5 days later): max {dm} characters, offers to map talent against an active JD.
7. call_opener: one permission-style opener (avoid "Is this a good time?").
8. call_bridge: 2 sentences in their language (hired for / measured on), tied to the verified signal, ending with a hypothesis question.
9. call_objections: 3 likely objections, each answered Acknowledge -> Probe -> Reframe -> Respond in at most 2 lines, ending with a question.

Return JSON only:
{{"email_1_subject": "", "email_1_body": "", "email_2_subject": "", "email_2_body": "",
"email_3_subject": "", "email_3_body": "", "linkedin_connection_note": "", "linkedin_followup_1": "",
"linkedin_followup_2": "", "call_opener": "", "call_bridge": "",
"call_objections": [{{"objection": "", "answer": ""}}]}}"""


EVAL_PROMPT = """You are a separate, strict reviewer of sales outreach (Art of Selling rubric). You did not write it.
Judge ONLY against the pack. Return JSON only.

PACK:
{pack}

DRAFTS:
{drafts}

1. Split email_1, email_2, email_3 and the LinkedIn note into sentences. Label each:
   "Evidence-backed" (supported by a [Verified] claim, or a question built on an [Assertion]),
   "Generic" (could be sent to anyone), or "Made up" (states as fact something not in the pack).
2. Score this rubric (points in brackets, total 100):
   opening_signal [15]: opens with a company/person-specific verified signal, not a generic role challenge
   distinct_specific [10]: each idea distinct and specific; no restated ideas
   peer_tone_no_filler [15]: peer-to-peer; no warm-up filler, flattery or sales language
   about_them [15]: about their problem; product is not the hero. The firm REQUIRES one short line stating
     its commercial model (fee or billing) in emails 1 and 2: do not penalise that line. Penalise only if the
     offer opens the email, takes more than one line, or crowds out their problem.
   one_low_ask_and_subject [15]: exactly one clear, low, specific ask per message; subjects would get opened
   sequence_adds_new [10]: each touch adds new information; no repetition
   right_length [10]: within limits for each channel
   personal_relevance [10]: at least one line relevant to this named person/company
   If ANY sentence is "Made up", the total must be 50 or less.
   Placeholders such as <first name>, [Name] or [Company] count as a failed message: total 40 or less.
3. List what to fix, split into fix_writing (rewrite instructions) and fix_research (missing facts).

Return: {{"sentences": [{{"message": "email_1", "text": "", "label": ""}}],
"rubric": {{"opening_signal": 0, "distinct_specific": 0, "peer_tone_no_filler": 0, "about_them": 0,
"one_low_ask_and_subject": 0, "sequence_adds_new": 0, "right_length": 0, "personal_relevance": 0}},
"score": 0, "fix_writing": [], "fix_research": [], "calibration": "is this eval likely too strict or too lenient, and why"}}"""

FILLER = re.compile(r"hope (you('| a)re|this finds)|i('m| am) reaching out|i wanted to|just checking in|"
                    r"let me know|touch base|circle back|hope all is well|i trust this", re.I)


def lint(msg):
    """Deterministic checks from the common-mistakes checklist, run on every draft."""
    issues = []
    limits = [("email_1_body", EMAIL_WORD_LIMIT), ("email_2_body", FOLLOWUP_WORD_LIMIT), ("email_3_body", 60)]
    for key, limit in limits:
        body = msg.get(key) or ""
        if not body.strip():
            issues.append("%s is empty" % key)
            continue
        if word_count(body) >= limit:
            issues.append("%s has %d words; keep it under %d" % (key, word_count(body), limit))
        if FILLER.search(body):
            issues.append("%s has warm-up filler or 'let me know' (%s)" % (key, FILLER.search(body).group(0)))
        paras = [p for p in body.split("\n") if p.strip()]
        if len(paras) > 1 and re.match(r"\s*(we|our|i am|i'm|at \w+,? we)\b", paras[1], re.I):
            issues.append("%s opens with us, not them" % key)
        if body.count("?") > 2:
            issues.append("%s has more than one ask" % key)
        if "!" in body:
            issues.append("%s uses exclamation marks" % key)
    for key in ("email_1_body", "email_2_body", "email_3_body", "linkedin_connection_note", "linkedin_followup_1",
                "linkedin_followup_2", "call_opener", "call_bridge"):
        if re.search(r"<[a-z ]+>|\[(name|company|your name|first name)\]", msg.get(key) or "", re.I):
            issues.append("%s contains a placeholder instead of a real name" % key)
    for key, limit in [("linkedin_connection_note", LINKEDIN_NOTE_LIMIT), ("linkedin_followup_1", LINKEDIN_DM_LIMIT),
                       ("linkedin_followup_2", LINKEDIN_DM_LIMIT)]:
        if len(msg.get(key) or "") > limit:
            issues.append("%s is %d characters; max %d" % (key, len(msg[key]), limit))
        if not (msg.get(key) or "").strip():
            issues.append("%s is empty" % key)
    for i in (1, 2, 3):
        if not (msg.get("email_%d_subject" % i) or "").strip():
            issues.append("email_%d_subject is empty" % i)
    return issues


def _write(pack, contact, profile, fixes):
    s = (json.loads(contact.get("signals") or "[]") if contact.get("signals") else [])
    role_hint = s[0]["role"] if s else "open"
    fix_block = ""
    if fixes:
        fix_block = "\nA reviewer graded your last version. Fix exactly these problems:\n- " + "\n- ".join(fixes) + "\n"
    prompt = WRITE_PROMPT.format(
        pack=pack_text(pack), track=contact.get("track", "permanent"), fee=profile["permanent_fee"],
        market=profile["typical_market_fee"], billing=profile["deputation_billing"],
        months=profile["deputation_minimum_months"], role_hint=role_hint, fix_block=fix_block,
        limit=EMAIL_WORD_LIMIT, flimit=FOLLOWUP_WORD_LIMIT, note=LINKEDIN_NOTE_LIMIT, dm=LINKEDIN_DM_LIMIT)
    return providers.gemini_json(prompt, settings.GEMINI_MODEL)


def _evaluate(pack, msg):
    drafts = {k: msg.get(k, "") for k in ("email_1_subject", "email_1_body", "email_2_subject", "email_2_body",
                                          "email_3_subject", "email_3_body", "linkedin_connection_note",
                                          "linkedin_followup_1", "linkedin_followup_2")}
    ev = providers.gemini_json(EVAL_PROMPT.format(pack=pack_text(pack), drafts=json.dumps(drafts, indent=1)),
                               settings.GEMINI_MODEL)
    rubric = ev.get("rubric") or {}
    score = sum(int(v or 0) for v in rubric.values()) if rubric else int(ev.get("score") or 0)
    labels = [x.get("label", "") for x in ev.get("sentences") or []]
    if any(l.lower().startswith("made") for l in labels):
        score = min(score, 50)
    issues = lint(msg)
    score = max(0, score - 3 * len(issues))  # deterministic checklist failures cost points too
    ev["score"] = score
    ev["lint"] = issues
    ev["counts"] = {k: sum(1 for l in labels if l.lower().startswith(k.lower()[:4]))
                    for k in ("Evidence-backed", "Generic", "Made up")}
    return ev


def ai_sequence(contact, profile, log):
    """Write -> separate eval -> fix input and rewrite, up to MAX_REWRITES times. Keeps the best version."""
    pack = build_pack(contact, profile)
    best, best_ev, fixes, loops = None, None, [], 0
    for loops in range(1, settings.MAX_REWRITES + 2):
        msg = _write(pack, contact, profile, fixes)
        ev = _evaluate(pack, msg)
        if best_ev is None or ev["score"] > best_ev["score"]:
            best, best_ev = msg, ev
        if ev["score"] >= settings.EVAL_THRESHOLD:
            break
        fixes = (ev.get("fix_writing") or [])[:6] + ev["lint"][:6]
        made_up = [x["text"] for x in ev.get("sentences") or [] if str(x.get("label", "")).lower().startswith("made")]
        if made_up:
            fixes.append("Delete or turn into a question these unsupported statements: " + " | ".join(made_up[:4]))
    best_ev["loops"] = loops
    return pack, best, best_ev


# ---------- Template fallback (no AI key, or the AI failed) ----------

def template_sequence(contact, profile):
    first = contact.get("first_name") or ("%s team" % contact["company"] if contact.get("company") else "there")
    company = contact.get("company") or "your team"
    try:
        signals = json.loads(contact.get("signals") or "[]")
    except ValueError:
        signals = []
    role = country = days = ""
    if signals:
        top = max(signals, key=lambda s: int(s.get("days_open") or 0))
        role, country, days = top.get("role", ""), _country(top.get("country", "")), top.get("days_open", "")
    elif contact.get("sample_roles"):
        m = re.match(r"(.+?) \((\w*), (\d+) days\)", contact["sample_roles"].split(" | ")[0])
        if m:
            role, country, days = m.group(1), _country(m.group(2)), m.group(3)
    perm = contact.get("track", "permanent") == "permanent"
    if role:
        hook = "%s %s role%s has been advertised for %s days." % (_possessive(company), role,
                                                                 " in " + country if country else "", days)
        agitate = ("Every extra week usually lands on the hiring manager and the crew covering the gap."
                   if perm else "Usually that means the rest of the crew is covering the gap while the schedule waits.")
        subject1 = "%s, %s days on" % (role, days)
    else:
        hook = "Specialist project roles in oil & gas often stay open far longer than planned."
        agitate = "The cost rarely shows in the budget; it shows in the schedule."
        subject1 = "Hard-to-fill roles at %s" % company
    offer = ("We fill permanent roles like this for %s, not the usual %s." % (profile["permanent_fee"], profile["typical_market_fee"])
             if perm else "We can put contract people on it (%s, minimum %s months), so it stays in OPEX."
             % (profile["deputation_billing"], profile["deputation_minimum_months"]))
    ask1 = ("Want me to send three anonymised profiles for the %s seat?" % role) if role else "Worth 15 minutes this week?"
    other = ("If a contract hire would be faster, we also deploy people for 6+ month assignments on man-month rates."
             if perm else "If you'd rather hire permanently, our fee is a flat one month's salary.")
    msg = {
        "email_1_subject": subject1,
        "email_1_body": "Hi %s,\n\n%s %s\n\n%s\n\n%s" % (first, hook, agitate, offer, ask1),
        "email_2_subject": "Another way to cover %s" % (role or "the gap"),
        "email_2_body": "Hi %s,\n\nWhen roles stay open this long, is it usually the candidate pool or the approval process holding things up?\n\n%s\n\nWorth a 15-minute call on Thursday?" % (first, other),
        "email_3_subject": "Right person?",
        "email_3_body": "Hi %s,\n\nIs hiring for %s something you look after, or should I speak to someone else?" % (first, role or "these projects"),
        "linkedin_connection_note": ("Hi %s, saw %s is hiring a %s in %s. I recruit for oil & gas projects across Africa, Asia, Europe and South America. Would be good to connect."
                                     % (first, company, role or "project team", country or "the region"))[:LINKEDIN_NOTE_LIMIT],
        "linkedin_followup_1": "Thanks for connecting, %s. Which roles on your current projects are proving hardest to fill right now?" % first,
        "linkedin_followup_2": "Hi %s, if you share an active JD, I'll map candidates we already know against it, no obligation." % first,
        "call_opener": "Hi %s, it's %s from %s. I have something specific about the %s role. Can I take 30 seconds?"
                       % (first, profile["sender_name"], profile["company_name"], role or "open project"),
        "call_bridge": "I saw the role has been advertised for %s days. When we speak to people in your seat, the real cost is the crew covering the gap. Is that what you're seeing?" % (days or "a while"),
        "call_objections": [
            {"objection": "We already use agencies.", "answer": "Makes sense. How is that working for this role, given it's been open a while? If it helps, we could send profiles for just this one seat."},
            {"objection": "Send me some info.", "answer": "Sure. So I send the right thing, how are you filling this today? Could we take 10 minutes on Thursday instead?"},
            {"objection": "No budget right now.", "answer": "Understood. Is the role still needed, or has it been parked? If it's needed, what is the gap costing you each week?"},
        ],
    }
    return msg


# ---------- Build rows ----------

def build_messages(contacts, profile, use_ai, log):
    """Writes contacts a few at a time (each needs several AI calls); keeps the original order."""
    from concurrent.futures import ThreadPoolExecutor
    workers = settings.AI_PARALLEL if use_ai else 1
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda c: _build_one(c, profile, use_ai, log), contacts))


def _build_one(c, profile, use_ai, log):
    pack = build_pack(c, profile)
    ev = None
    written_by = "AI"
    if use_ai:
        try:
            pack, msg, ev = ai_sequence(c, profile, log)
            log("  %s / %s: score %d after %d draft(s)" % (c.get("company"), c.get("first_name") or "inbox",
                                                           ev["score"], ev.get("loops", 1)))
        except providers.ProviderError as e:
            log("  AI failed for %s %s (%s), using template" % (c.get("first_name"), c.get("company"), e))
            msg, written_by = template_sequence(c, profile), "template (AI failed)"
    else:
        msg, written_by = template_sequence(c, profile), "template"
    if ev is None:
        issues = lint(msg)
        ev = {"score": "", "lint": issues, "fix_writing": [], "fix_research": [], "sentences": [], "counts": {},
              "calibration": "Not AI-checked: built-in template. Read it before sending.", "loops": 0}
    gdpr = is_gdpr(c)

    def full(body):
        return "%s\n\nBest,\n%s\n\n--\n%s" % ((body or "").strip(), signature(profile), footer(profile, gdpr))

    objections = msg.get("call_objections") or []
    row = {
        "review_status": "DRAFT - review before sending",
        "eval_score": ev.get("score", ""),
        "eval_pass": ("yes" if isinstance(ev.get("score"), int) and ev["score"] >= settings.EVAL_THRESHOLD
                      else ("not checked" if ev.get("score") == "" else "no")),
        "icp_fit": pack["icp_fit"],
        "lead_type": c.get("lead_type", ""),
        "pitch": "Permanent (one month's salary)" if c.get("track") == "permanent" else "Deputation (man-hour/month, 6+ months)",
        "first_name": c.get("first_name", ""), "last_name": c.get("last_name", ""),
        "title": c.get("title", ""), "company": c.get("company", ""),
        "email": c.get("email", ""), "email_status": c.get("email_status", ""),
        "linkedin_url": c.get("linkedin_url", ""),
        "oldest_days_open": c.get("oldest_days_open", ""),
        "email_subject": (msg.get("email_1_subject") or "").strip(),
        "email_body": full(msg.get("email_1_body")),
        "email_word_count": word_count(msg.get("email_1_body")),
        "email_2_subject": (msg.get("email_2_subject") or "").strip(),
        "email_2_body": full(msg.get("email_2_body")),
        "email_3_subject": (msg.get("email_3_subject") or "").strip(),
        "email_3_body": full(msg.get("email_3_body")),
        "linkedin_connection_note": (msg.get("linkedin_connection_note") or "").strip()[:LINKEDIN_NOTE_LIMIT],
        "linkedin_note_chars": len((msg.get("linkedin_connection_note") or "").strip()[:LINKEDIN_NOTE_LIMIT]),
        "linkedin_followup_1": (msg.get("linkedin_followup_1") or "").strip(),
        "linkedin_followup_2": (msg.get("linkedin_followup_2") or "").strip(),
        "call_opener": (msg.get("call_opener") or "").strip(),
        "call_bridge": (msg.get("call_bridge") or "").strip(),
        "call_objections": "\n".join("%s -> %s" % (o.get("objection", ""), o.get("answer", "")) for o in objections),
        "sequence_plan": "Day 1: LinkedIn connect + email 1 | Day 3: email 2 | Day 5: call if they opened/accepted | "
                         "Day 8: email 3 | After accept: LinkedIn follow-up 1, then 2 five days later",
        "verification_ratio": pack["verification_ratio"],
        "research_pack": pack_text(pack),
        "eval_counts": json.dumps(ev.get("counts") or {}),
        "eval_fix": "\n".join((ev.get("fix_writing") or []) + (ev.get("lint") or [])),
        "eval_research_gaps": "\n".join(ev.get("fix_research") or []),
        "eval_calibration": ev.get("calibration", ""),
        "eval_sentences": json.dumps(ev.get("sentences") or [])[:20000],
        "eval_loops": ev.get("loops", 0),
        "gdpr_notice_added": "yes" if gdpr else "no",
        "written_by": written_by,
        "signals": c.get("signals", ""),
        "track": c.get("track", ""),
    }
    return row


# ---------- Replies and objections ----------

REPLY_PROMPT = """A prospect replied to our outreach. Help the human respond, using the Art of Selling method.
Never send anything; this is a suggestion the human will edit.

WHO WE ARE: {us}
CONTACT: {who}
WHAT WE SENT (latest): {sent}
THEIR REPLY: {reply}

Do this:
1. Classify the reply: positive/meeting, send-info, not-interested, price, timing, already-have-supplier,
   wrong-person, unsubscribe, question, other.
2. If it is an objection, say which part of PSPA they didn't believe (Problem, Solution, Proof, Ask), and
   whether it is a risk ("what if" fear) rather than an objection.
3. Write a suggested reply: Acknowledge -> Probe -> Reframe -> Respond. Short (max 80 words), peer tone,
   never defensive, no discount, no price before value, end with ONE question or one small specific ask.
   If they asked to unsubscribe or said a firm no: a one-line polite confirmation only, no ask.
   Use only facts from WHO WE ARE; never invent clients, results or numbers, and never describe what
   "other operators", "clients" or "companies like you" do unless WHO WE ARE lists it as proof.
4. If a meeting is likely, give 5 discovery questions (Mom Test: past behaviour, quantified, not leading)
   covering BANT + Fit.
5. Next best action for the team (one line), and whether to mark the contact Do-not-contact.

Return JSON only: {{"classification": "", "pspa_gap": "", "is_risk": false, "suggested_reply": "",
"discovery_questions": [], "next_action": "", "do_not_contact": false}}"""


def handle_reply(row, reply_text, profile):
    pack_us = ("%s: oil & gas recruitment across %s. Permanent: %s. Contract deputation: %s, minimum %s months. Proof: %s"
               % (profile["company_name"], profile["regions_served"], profile["permanent_fee"],
                  profile["deputation_billing"], profile["deputation_minimum_months"],
                  "; ".join(profile.get("proof_points") or []) or "none, do not claim results"))
    who = "%s %s, %s at %s" % (row.get("first_name", ""), row.get("last_name", ""), row.get("title", ""), row.get("company", ""))
    sent = (row.get("email_subject", "") + "\n" + (row.get("email_body", "").split("\n\nBest,")[0]))[:1500]
    return providers.gemini_json(REPLY_PROMPT.format(us=pack_us, who=who, sent=sent, reply=reply_text[:3000]),
                                 settings.GEMINI_MODEL)
