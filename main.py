import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
import openai

# ======================================================
# LOGGING
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

openai.api_key = OPENAI_API_KEY
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ======================================================
# FASTAPI APP
# ======================================================
app = FastAPI()

# ======================================================
# LOAD SYSTEM INSTRUCTIONS
# ======================================================
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read().strip()
except Exception:
    logger.warning("instructions.txt not found — using fallback.")
    SYSTEM_INSTRUCTION = (
        "Anda ialah Penguatkuasa SSM Johor. "
        "Jawab berdasarkan garis panduan rasmi SSM Johor."
    )

# ======================================================
# SAFE TELEGRAM SENDER
# ======================================================
def send_telegram_message(chat_id: int, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=10)
        if not resp.ok:
            logger.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("send_telegram_message error: %s", e)


# ======================================================
# BUILD OPENAI MESSAGE
# ======================================================
def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]


# ======================================================
# CALL OPENAI (resilient version)
# ======================================================
def call_openai(messages):
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1200
    )
    return resp.choices[0].message["content"]


# ======================================================
# BACKGROUND PROCESSOR
# ======================================================
def process_and_reply(data: dict):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            return

        text = message.get("text") or message.get("caption", "")

        # Acknowledge quickly (background)
        try:
            send_telegram_message(chat_id, "Memproses permintaan anda... Sila tunggu sebentar.")
        except Exception:
            pass

        # Build & call OpenAI
        try:
            messages = build_openai_messages(text)
            ai_reply = call_openai(messages)
        except Exception as e:
            logger.exception("OpenAI call failed: %s", e)
            send_telegram_message(chat_id, "Maaf, berlaku ralat pada perkhidmatan AI. Sila cuba lagi kemudian.")
            return

        # Send reply (split if perlu)
        MAX_LEN = 3900
        if len(ai_reply) <= MAX_LEN:
            send_telegram_message(chat_id, ai_reply)
        else:
            buffer = ""
            for part in ai_reply.split("\n\n"):
                if len(buffer) + len(part) + 2 > MAX_LEN:
                    send_telegram_message(chat_id, buffer.strip())
                    buffer = part + "\n\n"
                else:
                    buffer += part + "\n\n"
            if buffer.strip():
                send_telegram_message(chat_id, buffer.strip())

    except Exception as e:
        logger.exception("Error in process_and_reply: %s", e)


# ======================================================
# ROOT ROUTES (prevent 502)
# ======================================================
@app.get("/")
async def root():
    return {"status": "SSM Telegram Bot Running ✔️"}

@app.get("/favicon.ico")
async def favicon():
    return {}


# ======================================================
# TELEGRAM WEBHOOK
# ======================================================
@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    try:
        data = await request.json()
    except Exception:
        # Return 200 so Telegram does not retry invalid payloads
        return {"ok": True}

    logger.info("Webhook received: keys=%s", list(data.keys()))
    # Queue the heavy work to background so we return fast
    try:
        background.add_task(process_and_reply, data)
    except Exception as e:
        logger.exception("Failed to schedule background task: %s", e)

    # Return immediately to Telegram
    return {"ok": True}
