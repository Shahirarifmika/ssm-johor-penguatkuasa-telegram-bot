# main.py (gantikan semua)
import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
import openai

# ======================================================
# CONFIG / LOGGING
# ======================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("ssm_bot")

# ======================================================
# ENV (Railway variables)
# ======================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
PORT = int(os.getenv("PORT", "8000"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY in environment")
    # exit so Railway shows an error instead of continuing a broken service
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in environment variables")

openai.api_key = OPENAI_API_KEY
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI(title="SSM Telegram Bot")

# ======================================================
# Helpers
# ======================================================
def send_telegram_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=10)
        if not resp.ok:
            logger.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("send_telegram_message error")

def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]

def call_openai(messages):
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1200
    )
    return resp.choices[0].message["content"]

# ======================================================
# Load system instruction (instructions.txt optional)
# ======================================================
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read().strip()
        logger.info("Loaded instructions.txt (%d chars)", len(SYSTEM_INSTRUCTION))
except Exception:
    SYSTEM_INSTRUCTION = "Anda ialah Penguatkuasa SSM Johor. Jawab mengikut arahan."
    logger.warning("instructions.txt not found — using fallback instruction")

# ======================================================
# Background worker
# ======================================================
def process_and_reply(data: dict):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            logger.info("No message field in update")
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            logger.warning("No chat id")
            return

        text = message.get("text") or message.get("caption", "") or ""
        logger.info("Processing message from chat_id=%s text_len=%d", chat_id, len(text))

        # quick ack
        try:
            send_telegram_message(chat_id, "Memproses permintaan anda... Sila tunggu sebentar.")
        except Exception:
            pass

        # call OpenAI
        try:
            msgs = build_openai_messages(text)
            reply = call_openai(msgs)
        except Exception:
            logger.exception("OpenAI call failed")
            send_telegram_message(chat_id, "Maaf, ralat perkhidmatan AI. Sila cuba lagi kemudian.")
            return

        # send reply, split large
        MAX_LEN = 3900
        if len(reply) <= MAX_LEN:
            send_telegram_message(chat_id, reply)
        else:
            buffer = ""
            for p in reply.split("\n\n"):
                if len(buffer) + len(p) + 2 > MAX_LEN:
                    send_telegram_message(chat_id, buffer.strip())
                    buffer = p + "\n\n"
                else:
                    buffer += p + "\n\n"
            if buffer.strip():
                send_telegram_message(chat_id, buffer.strip())

    except Exception:
        logger.exception("Unhandled error in process_and_reply")

# ======================================================
# Root / health routes (important to avoid 502)
# ======================================================
@app.get("/")
async def root():
    # Put minimal info so curl returns quickly
    return {"status": "SSM Telegram Bot Running ✔️", "port": PORT}

@app.get("/favicon.ico")
async def favicon():
    return {}

# ======================================================
# Webhook endpoint (immediate ack + background work)
# ======================================================
@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    try:
        data = await request.json()
    except Exception:
        logger.exception("Invalid JSON on webhook")
        # Return 200 so Telegram stops retrying bad payloads
        return {"ok": True}

    logger.info("Webhook received keys=%s", list(data.keys()))
    # enqueue background task
    try:
        background.add_task(process_and_reply, data)
    except Exception:
        logger.exception("Failed to add background task")

    # Return immediately (important)
    return {"ok": True}
