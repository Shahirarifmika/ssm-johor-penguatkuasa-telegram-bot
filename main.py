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
# ENV VARIABLES
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
# FASTAPI
# ======================================================
app = FastAPI()


# ======================================================
# LOAD SYSTEM INSTRUCTION
# ======================================================
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read().strip()
except:
    logger.warning("instructions.txt not found — using fallback.")
    SYSTEM_INSTRUCTION = (
        "Anda ialah Penguatkuasa SSM Johor. "
        "Jawab berdasarkan garis panduan rasmi SSM Johor."
    )


# ======================================================
# SEND TELEGRAM MESSAGE (SAFE)
# ======================================================
session = requests.Session()

def send_telegram_message(chat_id: int, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = session.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=10)
        if not r.ok:
            logger.error("sendMessage failed: %s %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("send_telegram_message error: %s", e)


# ======================================================
# OPENAI MESSAGE BUILDER
# ======================================================
def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]


# ======================================================
# CALL OPENAI
# ======================================================
def call_openai(messages):
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1500
    )
    return resp.choices[0].message["content"]


# ======================================================
# BACKGROUND PROCESS HANDLER
# ======================================================
def process_and_reply(data: dict):
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = message.get("text") or message.get("caption", "")

        # Initial ACK (wajib untuk tidak timeout Telegram)
        send_telegram_message(chat_id, "Memproses permintaan anda... ✔️")

        # OpenAI processing
        messages = build_openai_messages(text)
        reply = call_openai(messages)

        # Split panjang jika perlu
        MAX_LEN = 3900
        if len(reply) <= MAX_LEN:
            send_telegram_message(chat_id, reply)
        else:
            buffer = ""
            for part in reply.split("\n\n"):
                if len(buffer) + len(part) + 2 > MAX_LEN:
                    send_telegram_message(chat_id, buffer.strip())
                    buffer = part + "\n\n"
                else:
                    buffer += part + "\n\n"

            if buffer.strip():
                send_telegram_message(chat_id, buffer.strip())

    except Exception as e:
        logger.exception("process_and_reply error: %s", e)
        try:
            send_telegram_message(chat_id, "Maaf, berlaku ralat semasa memproses.")
        except:
            pass


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
# WEBHOOK ENDPOINT (WAJIB RETURN CEPAT)
# ======================================================
@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):

    try:
        data = await request.json()
    except:
        # Telegram akan retry jika 500 — kita avoid retri
        return {"ok": True}

    logger.info("Webhook received: keys=%s", list(data.keys()))

    # Queue heavy task
    background.add_task(process_and_reply, data)

    # ❗ RETURN CEPAT → SUPER PENTING
    return {"ok": True}
