import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
from openai import OpenAI  # Updated import

# ======================================================
# LOGGING & CONFIG
# ======================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("ssm_bot")

# ======================================================
# ENV VARIABLES (Railway)
# ======================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY in environment")
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in Railway variables")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ======================================================
# FASTAPI APP
# ======================================================
app = FastAPI()

# Rest of your existing code remains the same...
# [Keep all your existing functions: send_telegram_message, build_openai_messages, etc.]

# ======================================================
# UPDATE call_openai FUNCTION
# ======================================================
def call_openai(messages):
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1200
    )
    return resp.choices[0].message.content

# ======================================================
# RAILWAY DEPLOYMENT FIX
# ======================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
