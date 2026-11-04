import io
import pandas as pd
import os
import tempfile

import streamlit as st

from processor import process_pdf, category_summary

st.set_page_config(page_title="Bank Statement Processor", layout="wide")
st.title("Bank Statement Processor")
st.caption("Upload text or scanned PDF statements. Extraction + classification, no LLM.")

files = st.file_uploader("Upload bank statement PDF(s)", type="pdf", accept_multiple_files=True)
password = st.text_input("PDF password (only if protected)", type="password")

for f in files or []:
    st.divider()
    st.subheader(f.name)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(f.read())
    try:
        with st.spinner("Processing (scanned PDFs take longer because of OCR)..."):
            details, df, pdf_type = process_pdf(tmp.name, password or None)
    except Exception as e:
        st.error(f"Could not process this file: {e}")
        continue
    finally:
        os.unlink(tmp.name)

    st.info(f"Detected PDF type: **{pdf_type}-based**")
    st.write({k: v for k, v in details.items() if v})

    if df.empty:
        st.warning("No transactions found. The layout may be unsupported or the scan quality too low.")
        continue

    # Let the user fix categories before exporting
    cats = sorted(df["Category"].unique().tolist() + ["Other Income", "Other Expense"])
    df = st.data_editor(
        df, use_container_width=True, num_rows="dynamic", key=f.name,
        column_config={"Category": st.column_config.SelectboxColumn(options=sorted(set(cats)))})

    bad = (df["Balance Check"] == "CHECK").sum()
    if bad:
        st.warning(f"{bad} row(s) marked CHECK: running balance does not match. Review them (common with OCR).")

    c1, c2, c3 = st.columns(3)
    c1.metric("Transactions", len(df))
    c2.metric("Total debit", f"{df['Debit'].sum():,.2f}")
    c3.metric("Total credit", f"{df['Credit'].sum():,.2f}")
    st.dataframe(category_summary(df), use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, "Transactions", index=False)
        pd.DataFrame(details.items(), columns=["Field", "Value"]).to_excel(xw, "Account Details", index=False)
        category_summary(df).to_excel(xw, "Category Summary", index=False)
    d1, d2 = st.columns(2)
    d1.download_button("Download Excel", buf.getvalue(), f"{f.name[:-4]}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="x" + f.name)
    d2.download_button("Download CSV", df.to_csv(index=False), f"{f.name[:-4]}.csv", "text/csv", key="c" + f.name)
