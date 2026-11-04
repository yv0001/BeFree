"""Creates a text-based and a scanned (image-based) sample statement for testing."""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROWS = [
 ("01/04/2024","UPI/SWIGGY/4021/Dinner","450.00",None,49550.00),
 ("02/04/2024","ATM WDL 1234 MG ROAD",  "5,000.00",None,44550.00),
 ("05/04/2024","NEFT CR ACME TECH SALARY APR",None,"60,000.00",104550.00),
 ("07/04/2024","ECS HDFC HOME LOAN EMI","18,500.00",None,86050.00),
 ("10/04/2024","UPI/AMAZON PAY/Order 8892","1,299.00",None,84751.00),
 ("12/04/2024","BESCOM ELECTRICITY BILL","1,150.50",None,83600.50),
 ("15/04/2024","INT.PD 01-01-24 TO 31-03-24",None,"312.00",83912.50),
 ("18/04/2024","UPI/UBER INDIA/Trip","220.00",None,83692.50),
 ("20/04/2024","SMS ALERT CHARGES","17.70",None,83674.80),
]
def build(path):
    c = canvas.Canvas(path, pagesize=A4); w,h = A4; y=h-50
    for t in ["HDFC Bank - Statement of Account","Account Name: RAHUL SHARMA","Account No: 50100123456789",
              "IFSC: HDFC0001234","Statement Period: 01/04/2024 to 30/04/2024"]:
        c.setFont("Helvetica",11); c.drawString(40,y,t); y-=18
    y-=10; c.setFont("Helvetica",9)
    c.drawString(40,y,"Date"); c.drawString(110,y,"Narration"); c.drawString(330,y,"Withdrawal"); c.drawString(410,y,"Deposit"); c.drawString(490,y,"Balance"); y-=16
    c.drawString(40,y,"01/04/2024 Opening Balance 50,000.00"); y-=16
    for d,n,dr,cr,b in ROWS:
        c.drawString(40,y,d); c.drawString(110,y,n)
        c.drawRightString(380,y,dr or ""); c.drawRightString(460,y,cr or ""); c.drawRightString(550,y,f"{b:,.2f}"); y-=16
    c.save()
if __name__ == "__main__":
    import subprocess, os
    build("sample_text.pdf")
    # make an image-only (scanned) copy
    from pdf2image import convert_from_path
    convert_from_path("sample_text.pdf", dpi=200)[0].convert("L").save("sample_scanned.pdf")
    print("created sample_text.pdf and sample_scanned.pdf")
