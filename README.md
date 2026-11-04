# Bank Statement Processor (no LLM)

## Run
    pip install -r requirements.txt
    # OCR needs system tools: Tesseract + Poppler
    #   Windows: install Tesseract (UB-Mannheim build) and Poppler, add both to PATH
    #   Ubuntu : sudo apt install tesseract-ocr poppler-utils
    streamlit run app.py

Try `sample_text.pdf` and `sample_scanned.pdf` (made by `make_sample.py`).

## How it works
1. **Detect type** - if the PDF has a text layer -> pdfplumber; otherwise -> OCR (pdf2image + Tesseract).
2. **Account details** - regex for name, account no., IFSC, bank (from IFSC prefix), period.
3. **Transactions** - each line starting with a date is a row; trailing numbers are amount(s)+balance.
   Debit vs credit is decided by comparing with the previous balance (most reliable), then Dr/Cr markers, then keywords.
   Wrapped descriptions are merged; opening/closing/total lines are skipped; duplicates removed.
4. **Classification** - keyword rules in `RULES` (processor.py). First match wins; add keywords to extend.
   Unmatched -> "Other Income" / "Other Expense".
5. **Export** - Excel (Transactions, Account Details, Category Summary sheets) and CSV.

## Edge cases handled
Text vs scanned PDFs, password-protected PDFs, multiple files, many date formats, value-date column,
wrapped descriptions, separate/combined debit-credit columns, Dr/Cr suffixes, balance validation
(rows flagged `CHECK`, useful for OCR errors), editable categories in the UI before export.

## Limits / next steps
Tuned for the common "Date | Narration | Debit | Credit | Balance" layout. For unusual layouts add a
bank-specific parser; for better ML classification train a TF-IDF + LogisticRegression on corrected rows.
