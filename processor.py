"""Bank statement processor: PDF -> text (or OCR) -> transactions -> categories.
No LLMs used. Classification is rule/keyword based."""
import re
from datetime import datetime

import pandas as pd
import pdfplumber
from dateutil import parser as dateparser


import os
import shutil

# If Tesseract/Poppler are installed but not on PATH, set these env vars or edit the paths below.
POPPLER_PATH = os.environ.get("POPPLER_PATH") or None  # e.g. r"C:\poppler\Library\bin"
WINDOWS_TESSERACT = [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


def setup_ocr_paths(pytesseract):
    """Find Tesseract automatically (PATH, TESSERACT_CMD env var, or default Windows folders)."""
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd:
        cmd = next((p for p in WINDOWS_TESSERACT if os.path.exists(p)), None)
    if not cmd:
        raise RuntimeError("Tesseract OCR is not installed. Install it (see README) or upload a text-based PDF.")
    pytesseract.pytesseract.tesseract_cmd = cmd

# ---------------------------------------------------------------- 1. PDF TEXT

def detect_pdf_type(pdf_path, password=None):
    """'text' if the PDF has a real text layer, else 'image' (scanned)."""
    with pdfplumber.open(pdf_path, password=password) as pdf:
        chars = sum(len(p.extract_text() or "") for p in pdf.pages[:3])
        return "text" if chars > 100 else "image"


def read_lines(pdf_path, password=None):
    """Return (lines, pdf_type). Uses OCR automatically for scanned PDFs."""
    pdf_type = detect_pdf_type(pdf_path, password)
    lines = []
    if pdf_type == "text":
        with pdfplumber.open(pdf_path, password=password) as pdf:
            for page in pdf.pages:
                lines += (page.extract_text() or "").splitlines()
    else:
        import pytesseract
        from pdf2image import convert_from_path
        setup_ocr_paths(pytesseract)
        for img in convert_from_path(pdf_path, dpi=300, userpw=password, poppler_path=POPPLER_PATH):
            lines += pytesseract.image_to_string(img.convert("L"), config="--psm 6").splitlines()
    return [l.strip() for l in lines if l.strip()], pdf_type


# ---------------------------------------------------------- 2. ACCOUNT DETAILS

BANKS = {"HDFC": "HDFC Bank", "SBIN": "State Bank of India", "ICIC": "ICICI Bank",
         "UTIB": "Axis Bank", "KKBK": "Kotak Mahindra Bank", "PUNB": "Punjab National Bank",
         "BARB": "Bank of Baroda", "CNRB": "Canara Bank", "IDIB": "Indian Bank",
         "YESB": "Yes Bank", "INDB": "IndusInd Bank", "IDFB": "IDFC First Bank"}


def extract_account_details(lines):
    text = "\n".join(lines[:60])  # details are always at the top
    d = {}

    def find(pattern):
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else ""

    d["Account Holder"] = find(r"(?:account\s*(?:holder\s*)?name|customer\s*name|name)\s*[:\-]\s*([A-Za-z .]+)")
    d["Account Number"] = find(r"(?:a/?c|account)\s*(?:no|number|#)\.?\s*[:\-]?\s*(\d{6,18})") or find(r"(?:statement of account)\s+(\d{6,18})")
    d["IFSC"] = find(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
    d["Period"] = find(r"(?:period|statement\s*period)\s*[:\-]?\s*([^\n]+)")
    if not d["Account Holder"]:  # unlabeled name: an ALL-CAPS line followed by an address line
        for a, b in zip(lines[:30], lines[1:31]):
            if re.fullmatch(r"[A-Z][A-Z.\']+(?: [A-Z.\']+){1,3}", a) and re.match(r"\d", b):
                d["Account Holder"] = a.title()
                break
    d["Bank"] = BANKS.get(d["IFSC"][:4], "") if d["IFSC"] else ""
    if not d["Bank"]:
        for name in BANKS.values():
            if name.lower() in text.lower():
                d["Bank"] = name
                break
    return d


# ------------------------------------------------------------ 3. TRANSACTIONS

DATE_RE = re.compile(
    r"^(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[/\-]\d{1,2}(?=\s)|\d{1,2}[ \-][A-Za-z]{3,9}[ \-,]+\d{2,4})\s+")
AMOUNT = r"-?\$?\d[\d,]*\.\d{2}\s*(?:Cr|Dr|CR|DR)?"
TAIL_RE = re.compile(rf"((?:\s+{AMOUNT}){{1,3}})\s*$")
SKIP_RE = re.compile(r"opening balance|closing balance|brought forward|carried forward|"
                     r"page \d+|statement of account|total|beginning balance|ending balance|"
                     r"account\s*#|account transactions|activity for|^date\s|^description", re.I)


def to_num(s):
    return float(re.sub(r"[^\d.\-]", "", s))



def detect_dayfirst(lines):
    """Look at all dates: a first number >12 means DD/MM, a second number >12 means MM/DD."""
    for l in lines:
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})\b", l)
        if m:
            if int(m.group(1)) > 12:
                return True
            if int(m.group(2)) > 12:
                return False
    return True  # default: Indian DD/MM


def detect_year(lines):
    for l in lines:
        m = re.search(r"\b(20\d\d)\b", l)
        if m:
            return int(m.group(1))
    return datetime.now().year


def parse_date(text, dayfirst, year, last_month):
    """Parse a date; if the year is missing use the statement year and roll over at New Year."""
    has_year = bool(re.search(r"\d{4}|[/\-.]\d{2}$", text)) and len(re.split(r"[/\-. ]+", text.strip())) >= 3
    d = dateparser.parse(text, dayfirst=dayfirst, default=datetime(year, 1, 1))
    return d.date(), has_year

def parse_transactions(lines):
    rows, prev_balance, pending = [], None, None
    dayfirst, year, last_month = detect_dayfirst(lines), detect_year(lines), None
    extra = 0
    for line in lines:
        # opening balance may appear in a summary block (any line, not only dated ones)
        if prev_balance is None and not rows and re.search(r"opening balance|beginning balance", line, re.I):
            found = re.findall(AMOUNT, line)
            if found:
                prev_balance = to_num(found[0])
        m = DATE_RE.match(line)
        if not m and pending and TAIL_RE.search(line):  # merge pending date line + amount line
            line = pending[0].strftime("%d/%m/%Y") + " " + pending[1] + " " + line
            m = DATE_RE.match(line)
        if not m:
            # Wrapped description: append to previous transaction
            if SKIP_RE.search(line):
                extra = 99  # header/footer reached: stop attaching text to the last transaction
            elif rows and extra < 3 and not re.search(AMOUNT, line):
                rows[-1]["Description"] += " " + line
                extra += 1
            continue
        if SKIP_RE.search(line):
            # capture opening balance so the first row's debit/credit can be inferred
            t = TAIL_RE.search(line)
            if t and "opening" in line.lower():
                prev_balance = to_num(re.findall(AMOUNT, t.group(1))[-1])
            continue
        try:
            date, has_year = parse_date(m.group(1), dayfirst, year, last_month)
            if not has_year:  # statement spans a year end (e.g. Dec -> Jan)
                if last_month and date.month < last_month - 6:
                    year += 1
                    date = date.replace(year=year)
            last_month = date.month
        except Exception:
            continue
        rest = line[m.end():]
        rest = DATE_RE.sub("", rest, count=1)  # drop value-date column if present
        t = TAIL_RE.search(rest)
        if not t:  # date line without amounts: amounts appear on a following line
            pending = (date, rest)
            continue
        pending, extra = None, 0
        # OCR sometimes drops the dot of tiny amounts (".26" read as "26"): repair using the balance
        if len(re.findall(AMOUNT, t.group(1))) == 1 and prev_balance is not None:
            tok = re.search(r"\s\.?(\d{1,2})$", rest[:t.start()])
            if tok:
                small = float("0." + tok.group(1).zfill(2))
                bal = to_num(re.findall(AMOUNT, t.group(1))[0])
                if abs(prev_balance + small - bal) < 0.01 or abs(prev_balance - small - bal) < 0.01:
                    rest = rest[:t.start()][:tok.start()] + f" {small:.2f}" + t.group(1)
                    t = TAIL_RE.search(rest)
        amts = re.findall(AMOUNT, t.group(1))
        desc = rest[:t.start()].strip()
        nums = [to_num(a) for a in amts]
        row = {"Date": date, "Description": desc, "Debit": 0.0, "Credit": 0.0, "Balance": None}

        if len(nums) >= 2:
            balance, amt = nums[-1], abs(nums[-2])
            row["Balance"] = balance
            # Most reliable method: compare against previous balance
            if prev_balance is not None and abs(prev_balance - amt - balance) < 0.01:
                row["Debit"] = amt
            elif prev_balance is not None and abs(prev_balance + amt - balance) < 0.01:
                row["Credit"] = amt
            else:  # fall back to Dr/Cr marker or keywords
                if re.search(r"\bdr\b", amts[-2], re.I) or guess_is_debit(desc):
                    row["Debit"] = amt
                else:
                    row["Credit"] = amt
            if len(nums) == 3 and nums[0] and nums[1]:  # explicit debit & credit columns
                row["Debit"], row["Credit"] = abs(nums[0]), abs(nums[1])
            prev_balance = balance
        else:  # only one amount, no balance column
            amt = abs(nums[0])
            if re.search(r"\bcr\b", amts[0], re.I) or not guess_is_debit(desc):
                row["Credit"] = amt
            else:
                row["Debit"] = amt
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Some statements repeat transactions in a second summary table without a balance column: keep the main one
    if df["Balance"].notna().any():
        df = df[df["Balance"].notna()]
    df = df.drop_duplicates().reset_index(drop=True)
    df["Description"] = df["Description"].str.replace(r"\s+", " ", regex=True).str.strip()
    return df


def guess_is_debit(desc):
    d = desc.lower()
    credit_words = ("credit", "salary", "refund", "interest", "cashback", "deposit", "received", "by transfer", "neft cr", "imps cr")
    return not any(w in d for w in credit_words)


def validate_balances(df):
    """Flag rows where previous balance +/- amount != this balance."""
    ok = []
    for i, r in df.iterrows():
        if i == 0 or pd.isna(r["Balance"]) or pd.isna(df.loc[i - 1, "Balance"]):
            ok.append("")
            continue
        expected = df.loc[i - 1, "Balance"] - r["Debit"] + r["Credit"]
        ok.append("" if abs(expected - r["Balance"]) < 0.01 else "CHECK")
    df["Balance Check"] = ok
    return df


# ------------------------------------------------------------ 4. CLASSIFIER

# Order matters: first match wins. Easy to extend - just add keywords.
RULES = [
    ("Salary", ["salary", "payroll", "sal credit"]),
    ("EMI / Loan", ["emi", "loan", "nach", "ecs"]),
    ("Rent", ["rent", "landlord"]),
    ("ATM Withdrawal", ["atm", "cash wdl", "cash withdrawal", "nwd", "eaw"]),
    ("Cash Deposit", ["cash deposit", "cdm", "cash dep"]),
    ("Food & Dining", ["swiggy", "zomato", "restaurant", "cafe", "dominos", "mcdonald", "pizza", "starbucks"]),
    ("Groceries", ["bigbasket", "blinkit", "zepto", "dmart", "grocery", "reliance fresh", "instamart"]),
    ("Shopping", ["amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa"]),
    ("Travel", ["uber", "ola", "irctc", "makemytrip", "redbus", "indigo", "airlines", "fuel", "petrol", "hpcl", "bpcl", "iocl", "fastag"]),
    ("Bills & Utilities", ["electricity", "bescom", "recharge", "airtel", "jio", "vodafone", "broadband", "gas bill", "water bill", "dth", "bill pay", "billdesk"]),
    ("Entertainment", ["netflix", "spotify", "hotstar", "prime video", "bookmyshow", "youtube", "pvr", "inox"]),
    ("Insurance", ["insurance", "lic", "premium", "policybazaar"]),
    ("Investments", ["mutual fund", "sip", "zerodha", "groww", "upstox", "nps", "ppf", "demat"]),
    ("Healthcare", ["pharmacy", "hospital", "apollo", "medplus", "clinic", "diagnostic", "1mg", "pharmeasy"]),
    ("Education", ["school", "college", "university", "tuition", "udemy", "coursera", "fees"]),
    ("Bank Charges", ["charge", "charges", "chg", "gst", "fee", "penalty", "sms alert", "annual fee", "min bal"]),
    ("Interest", ["interest", "int.pd", "int pd", "int credit"]),
    ("Refund / Cashback", ["refund", "reversal", "cashback"]),
    ("Cheque", ["chq", "cheque", "check", "clearing"]),
    ("Card / POS Purchase", ["pos purchase", "pos", "debit card", "card purchase"]),
    ("UPI Transfer", ["upi"]),
    ("Online Transfer", ["neft", "imps", "rtgs", "transfer", "trf"]),
]


def classify(description, debit, credit):
    d = description.lower()
    for category, words in RULES:
        if any(re.search(rf"\b{re.escape(w)}", d) for w in words):
            return category
    return "Other Income" if credit > 0 else "Other Expense"


# -------------------------------------------------------------- 5. PIPELINE

def process_pdf(pdf_path, password=None):
    lines, pdf_type = read_lines(pdf_path, password)
    details = extract_account_details(lines)
    df = parse_transactions(lines)
    if not df.empty:
        df["Category"] = [classify(r.Description, r.Debit, r.Credit) for r in df.itertuples()]
        df = validate_balances(df)
    return details, df, pdf_type


def category_summary(df):
    return (df.groupby("Category")[["Debit", "Credit"]].sum()
              .assign(Count=df.groupby("Category").size())
              .sort_values("Debit", ascending=False).reset_index())