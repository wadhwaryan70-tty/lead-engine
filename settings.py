"""Targeting settings. Edit these lists to change who the engine looks for."""
import os
import shutil

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Results, history, your lists, keys and company details live here (a persistent disk when hosted).
DATA_ROOT = os.environ.get("DATA_ROOT") or APP_DIR


def profile_path():
    """company_profile.json in the data folder, seeded from the default on first use."""
    path = os.path.join(DATA_ROOT, "company_profile.json")
    if not os.path.exists(path):
        os.makedirs(DATA_ROOT, exist_ok=True)
        shutil.copy(os.path.join(APP_DIR, "company_profile.json"), path)
    return path

# How long a role must have been open to count as a high-intent lead.
MIN_DAYS_OPEN = 30
# Roles older than this are probably filled or dead, so they're skipped.
MAX_DAYS_OPEN = 120

# Countries by region (ISO-2 codes). The US is never included.
# Iran, Russia and Venezuela are left out because of sanctions.
REGIONS = {
    "Asia & Middle East": ["IN", "CN", "KZ", "AZ", "PK", "BD", "JP", "KR",
                           "AE", "SA", "QA", "OM", "KW", "BH", "IQ"],
    "Southeast Asia": ["ID", "MY", "SG", "TH", "VN", "PH", "BN", "MM"],
    "Africa": ["NG", "AO", "GH", "EG", "DZ", "LY", "MZ", "TZ", "SN", "CG",
               "GA", "GQ", "CM", "ZA", "NA", "UG", "KE", "CI"],
    "Europe": ["GB", "NO", "NL", "DK", "DE", "FR", "IT", "RO", "PL", "IE",
               "ES", "PT", "CY", "GR", "TR"],
    "South America": ["BR", "GY", "SR", "AR", "CO", "PE", "EC", "CL", "BO", "UY"],
}
EXCLUDED_COUNTRIES = ["US"]

# Contacts in these countries get a GDPR-style "why you're hearing from us"
# line and an opt-out in every email.
GDPR_COUNTRIES = {"GB", "NO", "NL", "DK", "DE", "FR", "IT", "RO", "PL", "IE",
                  "ES", "PT", "CY", "GR", "BE", "SE", "FI", "AT", "CH", "IS"}

# Client companies: operators, EPC contractors and service companies.
# The hiring company must be in one of these industries (TheirStack / LinkedIn industry IDs)...
CLIENT_INDUSTRY_IDS = [
    57,    # Oil and Gas
    332,   # Oil, Gas, and Mining
    3095,  # Oil Extraction
    3096,  # Natural Gas Extraction
    679,   # Oil and Coal Product Manufacturing (refining)
    1262,  # Wholesale Petroleum and Petroleum Products
    397,   # Natural Gas Distribution
    1520,  # Pipeline Transportation
    385,   # Fossil Fuel Electric Power Generation
    48,    # Construction (EPC contractors)
    419,   # Utility System Construction
    3242,  # Engineering Services (EPC / engineering contractors)
    58,    # Shipbuilding (offshore fabrication yards)
    95,    # Maritime Transportation (offshore vessels)
    2247,  # Commercial and Industrial Machinery Maintenance (service companies)
]
# ...and never a recruiter (they're competitors, not clients).
EXCLUDED_INDUSTRY_IDS = [104, 137, 123]  # Staffing and Recruiting, HR Services, Outsourcing
EXCLUDED_COMPANY_NAME = r"recruit|staffing|manpower|talent|resourc|personnel|headhunt|career|jobs|hiring|private advertiser|confidential|undisclosed"

# ...and the job ad must clearly be oil & gas work (so construction and engineering
# firms only count when the role is on an oil & gas project).
SECTOR_PATTERNS = [
    r"oil (and|&|/) ?gas", r"\bpetroleum\b", r"\bupstream\b", r"\bmidstream\b",
    r"\bdownstream\b", r"\bFPSO\b", r"\bLNG\b", r"\bsubsea\b", r"\brefiner(y|ies)\b",
    r"\bpetrochemical", r"\bwellhead\b", r"\bhydrocarbon", r"\boilfield\b",
    r"\bdrilling rig\b", r"\boffshore platform\b", r"\bgas processing\b", r"\boil field\b",
    r"\bjack-?up\b", r"\bwell (intervention|services|testing|completion)\b",
]

# Job titles that count as "critical project roles". Words in one entry must
# all appear in the title, in any order.
CRITICAL_ROLE_TITLES = [
    "project manager", "project director", "project engineer",
    "commissioning", "construction manager", "site manager",
    "drilling engineer", "drilling supervisor", "rig manager", "toolpusher",
    "offshore installation manager", "HSE", "QA/QC", "piping engineer",
    "mechanical engineer", "electrical engineer", "instrument engineer",
    "process engineer", "subsea engineer", "pipeline engineer",
    "operations manager", "maintenance manager", "planner", "superintendent",
    "technician", "supervisor",
]

# Titles with these words are skipped (not critical project roles).
EXCLUDED_TITLE_WORDS = ["intern", "internship", "campus", "graduate", "trainee", "apprentice", "student"]

# Decision-makers to find at each hiring company, split by which pitch they get.
# "permanent" -> Cost of Open Vacancy email (one month's salary flat fee)
# "deputation" -> Rapid Mobilization email (man-hour / man-month, 6-month minimum)
DECISION_MAKER_TITLES = {
    "permanent": [
        "HR Director", "Head of HR", "HR Manager", "Talent Acquisition Manager",
        "Head of Talent Acquisition", "Recruitment Manager", "Operations Director",
        "Country Manager", "General Manager",
    ],
    "deputation": [
        "Project Director", "Project Manager", "Rig Manager",
        "Commissioning Manager", "Construction Manager", "Operations Manager",
        "Offshore Installation Manager", "Drilling Manager", "Site Manager",
    ],
}
# Titles matching this go to the permanent pitch; everyone else gets deputation.
PERMANENT_TRACK_PATTERN = r"\b(HR|human resources|talent|recruit|people|general manager|country manager|operations director)\b"

# Cost controls (each paid API call uses credits).
JOBS_PER_RUN = 100            # TheirStack jobs pulled per run (1 credit each)
JOBS_PAGE_SIZE = 25           # TheirStack free plan allows max 25 per request
DECISION_MAKERS_PER_COMPANY = 3
MAX_COMPANIES_PER_RUN = 25

# Don't draft to the same person again within this many days.
RECONTACT_AFTER_DAYS = 90

# Free email finder. The mailbox check asks the company's mail server whether an address
# exists (no email is sent). Turn off if your network blocks port 25.
VERIFY_MAILBOX_SMTP = True
SMTP_MAX_GUESSES = 4          # address formats tried per person
SMTP_HELO_DOMAIN = "localhost"  # replaced with your website from company_profile.json at run time
CRAWL_COMPANY_WEBSITES = True  # look for hr@/careers@ emails on company websites

# Drafts are graded by a separate AI pass (0-100, Art of Selling rubric). Below the threshold they are
# rewritten with the reviewer's fixes, up to MAX_REWRITES times; the best version is kept.
EVAL_THRESHOLD = 75
MAX_REWRITES = 3
AI_PARALLEL = 3              # contacts written at the same time

GEMINI_MODEL = "gemini-3.8-flash"


# Adzuna (free backup job source) covers these of our target countries.
ADZUNA_COUNTRIES = ["GB", "IN", "SG", "ZA", "BR", "NL", "DE", "FR", "IT", "ES", "PL"]
ADZUNA_CATEGORY = "energy-oil-gas-jobs"
ADZUNA_KEYWORDS = "oil gas petroleum offshore drilling LNG refinery subsea FPSO petrochemical upstream"
ADZUNA_MAX_CALLS_PER_RUN = 20   # free plan has daily/monthly hit limits; 1 call = up to 50 ads
ADZUNA_PAGES_PER_COUNTRY = 2


def all_target_countries():
    codes = []
    for region_codes in REGIONS.values():
        codes.extend(c for c in region_codes if c not in EXCLUDED_COUNTRIES)
    return codes


def pick_countries(countries=None, regions=None):
    """Countries chosen on the command line (--countries / --region), else every target country."""
    chosen = []
    for r in regions or []:
        match = [name for name in REGIONS if r.lower() in name.lower()]
        if not match:
            raise ValueError("Unknown region '%s'. Options: %s" % (r, ", ".join(REGIONS)))
        for name in match:
            chosen += REGIONS[name]
    for c in countries or []:
        c = c.strip().upper()
        if c in EXCLUDED_COUNTRIES:
            raise ValueError("%s is excluded from targeting." % c)
        if c and c not in chosen:
            chosen.append(c)
    return [c for c in dict.fromkeys(chosen)] or all_target_countries()


def region_for(country_code):
    for region, codes in REGIONS.items():
        if country_code in codes:
            return region
    return ""


COUNTRY_NAMES = {
    "IN": "India", "CN": "China", "KZ": "Kazakhstan", "AZ": "Azerbaijan", "PK": "Pakistan",
    "BD": "Bangladesh", "JP": "Japan", "KR": "South Korea", "AE": "the UAE", "SA": "Saudi Arabia",
    "QA": "Qatar", "OM": "Oman", "KW": "Kuwait", "BH": "Bahrain", "IQ": "Iraq", "ID": "Indonesia",
    "MY": "Malaysia", "SG": "Singapore", "TH": "Thailand", "VN": "Vietnam", "PH": "the Philippines",
    "BN": "Brunei", "MM": "Myanmar", "NG": "Nigeria", "AO": "Angola", "GH": "Ghana", "EG": "Egypt",
    "DZ": "Algeria", "LY": "Libya", "MZ": "Mozambique", "TZ": "Tanzania", "SN": "Senegal",
    "CG": "Congo", "GA": "Gabon", "GQ": "Equatorial Guinea", "CM": "Cameroon", "ZA": "South Africa",
    "NA": "Namibia", "UG": "Uganda", "KE": "Kenya", "CI": "Cote d'Ivoire", "GB": "the UK",
    "NO": "Norway", "NL": "the Netherlands", "DK": "Denmark", "DE": "Germany", "FR": "France",
    "IT": "Italy", "RO": "Romania", "PL": "Poland", "IE": "Ireland", "ES": "Spain", "PT": "Portugal",
    "CY": "Cyprus", "GR": "Greece", "TR": "Turkey", "BR": "Brazil", "GY": "Guyana", "SR": "Suriname",
    "AR": "Argentina", "CO": "Colombia", "PE": "Peru", "EC": "Ecuador", "CL": "Chile", "BO": "Bolivia",
    "UY": "Uruguay",
}
