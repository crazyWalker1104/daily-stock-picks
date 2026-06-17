"""Send a test email via 163 SMTP"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("SMTP_HOST", "")
port = int(os.getenv("SMTP_PORT", "465"))
user = os.getenv("SMTP_USER", "")
pwd = os.getenv("SMTP_PASSWORD", "")
to = os.getenv("RECIPIENT_EMAIL", "")

msg = MIMEMultipart("alternative")
msg["Subject"] = "[Test] Daily Stock Picks - Email Test"
msg["From"] = user
msg["To"] = to

html_body = """
<h2>Email Test</h2>
<p>If you see this, SMTP email sending <b>works</b>!</p>
<hr>
<p>From: Daily Stock Picks system</p>
"""
msg.attach(MIMEText("Email Test - plain text fallback", "plain", "utf-8"))
msg.attach(MIMEText(html_body, "html", "utf-8"))

try:
    server = smtplib.SMTP_SSL(host, port, timeout=15)
    server.login(user, pwd)
    server.sendmail(user, [to], msg.as_string())
    server.quit()
    print(f"[OK] Test email sent to {to}")
    print("-> Check your inbox AND spam folder at mail.163.com")
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
