# Oil & Gas Lead Engine

Finds energy companies (outside the US) with critical roles open for 30+ days, finds the people who
control hiring there (work email + LinkedIn), cleans your old prospect list, and writes a cold email
plus a LinkedIn sequence for each person. Everything is saved as CSV files.

## One-time setup
1. Copy `.env.example` to `.env` and paste in your three API keys (TheirStack, Apollo, Gemini).
2. Fill in `company_profile.json` with your firm's details. Add any real proof points (placements,
   named clients, replacement guarantee). The emails only use what you put here.
3. Put your old prospect exports (any CSV from your CRM or spreadsheet) in `input/old_prospects/`.
   Column names are matched automatically (Name, Email, Company, Title, Country, Status, Notes...).

## Each run
```bash
python3 run.py
```
Options:
| Option | What it does |
|---|---|
| `--sample` | Test run on example data, no keys needed |
| `--old-only` | Only re-engage your old prospects (needs just the Gemini key) |
| `--no-ai` | Use the built-in templates instead of Gemini |
| `--max-jobs 50` | Pull fewer job ads to save TheirStack credits |
| `--max-companies 10` | Find contacts at fewer companies to save Apollo credits |
| `--include-recent` | Also redo people who already got a draft in the last 90 days |
| `--credits` | Just show how many credits each service has left |
| `--countries NG,AO,GB` | Search only these countries |
| `--region Africa` | Search only one region (repeat for more: `--region Africa --region Europe`) |
| `--list-countries` | Show every country code by region, and which job source covers it |
| `--source adzuna` | Job source: `auto` (default: TheirStack, then Adzuna when credits run out), `theirstack`, `adzuna`, or `both` |

Example: open roles in Nigeria and Angola only, using Adzuna's free search where it covers them:
```bash
python3 run.py --countries NG,AO
```

## Credits
Every run starts and ends with a credit panel (also saved as `00_credit_usage.csv`):
```
 TheirStack jobs  [############------------] 96/200 used | 104 left | renews 2026-12-02 | OK
```
If TheirStack credits run low, the run pulls only what's left. At zero it switches to **Adzuna**
(free) when its keys are set, otherwise it skips the job search and still works on your old prospects
and the people you add yourself.

Adzuna covers the UK, India, Singapore, South Africa, Brazil, the Netherlands, Germany, France,
Italy, Spain and Poland. It gives company names only, so the engine finds each company's website
itself before looking for emails.

## Finding emails for free
Apollo's free plan doesn't allow contact lookups, so the engine finds emails itself:
1. Emails printed in the job ad (the inbox that owns the vacancy).
2. The company's hiring or general inbox from its website.
3. For named people: works out the company's email format and asks the company's mail server
   whether the address exists (no email is sent). Confirmed addresses are marked `verified`.

To add people you found yourself (e.g. via the search links in `02_target_companies_ranked.csv`),
put them in `input/people_to_find.csv` with columns `first_name, last_name, title, company, website,
linkedin_url, country` (see `input/people_to_find.example.csv`). The next run finds their emails.

Anyone who gets a draft is remembered in `data/outreach_history.csv` and skipped for 90 days
(change `RECONTACT_AFTER_DAYS` in `settings.py`).

## What you get (in `output/<date>/`)
| File | What it is |
|---|---|
| 00_search_playbook.csv | 5 Google X-Ray strings, 5 LinkedIn Boolean strings, 5 non-US job boards |
| 01_open_roles_30plus_days.csv | Every oil & gas role open 30-120 days in your target regions, with link |
| 02_target_companies_ranked.csv | Companies ranked by how many stale roles they have and how old |
| 03_new_prospects.csv | Decision-makers at those companies: email, LinkedIn, which pitch they get |
| 04_old_prospects_to_reengage.csv | Your old list, de-duplicated; HOT = their company has stale vacancies now |
| 04b_old_prospects_removed.csv | Duplicates and do-not-contact rows that were taken out, with the reason |
| 05_outreach_messages.csv | Email subject + body, LinkedIn note (300 chars) and 2 follow-ups per person |
| 06_email_send_list.csv | Confirmed emails (verified, from job ads, from company websites) with subject + body, ready to import into Gmail mail merge, Instantly or Lemlist |
| 06b_guessed_emails_check_first.csv | Emails built from the company's format but not confirmed. Send slowly or check them first |
| 07_linkedin_tasks.csv | Your LinkedIn to-do list: profile link, connection note, and when to send each follow-up |

HR/talent leaders get the **permanent** pitch (flat fee of one month's salary). Project and operations
managers get the **deputation** pitch (man-hour/man-month billing, 6-month minimum).

## How drafts are written (Art of Selling method)
Each contact gets a research pack (every fact marked Verified with source and date, or Assertion used only
as a question), then a sequence: 3 emails (day 1 / 3 / 8), a LinkedIn note and 2 follow-ups, and a call
script with objection answers. A separate AI pass labels every sentence (Evidence-backed / Generic / Made up)
and scores the sequence out of 100; below 75 it is rewritten with the fixes, up to 3 times. In the app,
"They replied" suggests an answer (acknowledge, probe, reframe, respond). To redo drafts after changing
settings: `python3 run.py --redraft 2026-11-02_1729` or the button on the Results page.

## Before you send
- Every message is a draft. Read it, and open the job link to confirm the role is still live.
- EU/UK/Norway contacts get a "why you're hearing from us" line; everyone gets an opt-out.
- Send from a separate outreach domain, not your main one, and keep it under ~50 emails a day per
  mailbox at first.
- LinkedIn messages are for you to paste in by hand. Automating LinkedIn risks a ban.

## Changing who it targets
Edit `settings.py`: countries per region, role titles, decision-maker titles, and how many
companies and contacts each run pulls (this controls API credit spend).
