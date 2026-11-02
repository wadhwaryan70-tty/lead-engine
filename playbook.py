"""Pillar 1 search strings and job boards, written to CSV for manual prospecting."""

XRAY_STRINGS = [
    ("Africa - project leaders",
     'site:linkedin.com/in ("Project Director" OR "Project Manager") ("offshore" OR "onshore") '
     '("oil and gas" OR "EPC") ("Nigeria" OR "Angola" OR "Ghana" OR "Mozambique") -recruiter'),
    ("Southeast Asia - drilling",
     'site:linkedin.com/in ("Rig Manager" OR "Drilling Superintendent" OR "Drilling Manager") '
     '("Malaysia" OR "Indonesia" OR "Brunei" OR "Thailand" OR "Vietnam") -recruiter'),
    ("Asia & Middle East - commissioning",
     'site:linkedin.com/in ("Commissioning Manager" OR "Construction Manager") ("LNG" OR "FPSO" OR "refinery") '
     '("Qatar" OR "UAE" OR "Saudi Arabia" OR "Oman" OR "India") -recruiter'),
    ("Europe - HR & talent",
     'site:linkedin.com/in ("HR Director" OR "Head of Talent Acquisition" OR "HR Manager") '
     '("oil and gas" OR "offshore" OR "drilling") ("Norway" OR "Aberdeen" OR "Netherlands" OR "Romania") -recruitment'),
    ("South America - leadership",
     'site:linkedin.com/in ("Project Director" OR "Country Manager" OR "Operations Director") '
     '("oil and gas" OR "offshore" OR "subsea") ("Brazil" OR "Guyana" OR "Suriname" OR "Argentina")'),
]

LINKEDIN_BOOLEAN = [
    ("Project leaders (EPC)",
     '("Project Director" OR "Project Manager" OR "Package Manager") AND ("EPC" OR "EPCI" OR "offshore" OR "onshore") '
     'NOT (recruiter OR recruitment OR sales)'),
    ("Rig & drilling",
     '("Rig Manager" OR "OIM" OR "Offshore Installation Manager" OR "Drilling Superintendent" OR "Drilling Manager") '
     'NOT (recruiter OR consultant)'),
    ("Commissioning",
     '("Commissioning Manager" OR "Start-up Manager" OR "Completions Manager") AND ("LNG" OR "FPSO" OR "refinery" OR "gas plant")'),
    ("HR / talent in energy",
     '("HR Director" OR "Head of HR" OR "Talent Acquisition Manager" OR "Head of Resourcing") AND '
     '("oil" OR "gas" OR "energy" OR "drilling" OR "offshore") NOT (agency OR "recruitment consultant")'),
    ("Service company leadership",
     '("Operations Director" OR "Country Manager" OR "General Manager") AND '
     '("oilfield services" OR "well services" OR "subsea" OR "marine")'),
]

JOB_BOARDS = [
    ("Rigzone", "rigzone.com/oil/jobs", "Global",
     "Sort by date and filter by country; ads list a posted date, so anything older than 30 days is a lead."),
    ("Energy Jobline", "energyjobline.com", "Europe, Middle East, Africa",
     "Filter Oil & Gas + location; check the posted date on each ad."),
    ("Oil and Gas Job Search", "oilandgasjobsearch.com", "Global",
     "Filter by region and discipline; the same ad reposted month after month signals a stuck role."),
    ("Bayt / NaukriGulf", "bayt.com, naukrigulf.com", "Middle East & India",
     "Search 'oil gas' + city; set date filter to 'older than 30 days' or sort oldest first."),
    ("JobStreet / MyJobMag", "jobstreet.com (SEA), myjobmag.com (Africa)", "Southeast Asia, Africa",
     "Search by sector + country and note ads still live after 30 days."),
]


def rows():
    out = []
    for name, s in XRAY_STRINGS:
        out.append({"type": "Google X-Ray (paste into Google)", "target": name, "search_or_site": s, "how_to_use": "Change countries to switch region. Never add US locations."})
    for name, s in LINKEDIN_BOOLEAN:
        out.append({"type": "LinkedIn Boolean (Title field)", "target": name, "search_or_site": s, "how_to_use": "Paste into the Title filter, then set Geography to your target regions."})
    for name, url, region, how in JOB_BOARDS:
        out.append({"type": "Job board (non-US)", "target": "%s - %s" % (name, region), "search_or_site": url, "how_to_use": how})
    return out
