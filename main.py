import os
import logging
import requests
from fastapi import FastAPI, Request, BackgroundTasks
import openai

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ssm_bot")

# Environment variables (set these in Railway Variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # change if needed

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY in environment")
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in environment variables")

openai.api_key = OPENAI_API_KEY
TG_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI()

# Load system instruction from file (instructions.txt)
SYSTEM_INSTRUCTION = ""
try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read()
except Exception as e:
    logger.warning("instructions.txt not found or unreadable; using fallback.")
    SYSTEM_INSTRUCTION = "Anda ialah Penguatkuasa SSM Johor. Jawab mengikut arahan."

def send_telegram_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=payload, timeout=10)
        if not resp.ok:
            logger.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending telegram message: %s", e)

def build_openai_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_text}
    ]

def call_openai(messages):
    # ChatCompletion API
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=1000
    )
    return resp.choices[0].message["content"]

@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    data = await request.json()
    logger.info("Received webhook: keys=%s", list(data.keys()))
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        # quick ack
        send_telegram_message(chat_id, "Memproses permintaan anda... Sila tunggu sebentar.")
        # background process
        def process_and_reply(chat_id, text):
            try:
                messages = build_openai_messages(text)
                reply = call_openai(messages)
                # split long replies for Telegram limit
                MAX_LEN = 4000
                if len(reply) <= MAX_LEN:
                    send_telegram_message(chat_id, reply)
                else:
                    parts = reply.split("\n\n")
                    buffer = ""
                    for p in parts:
                        if len(buffer) + len(p) + 2 > MAX_LEN:
                            send_telegram_message(chat_id, buffer.strip())
                            buffer = p + "\n\n"
                        else:
                            buffer += p + "\n\n"
                    if buffer.strip():
                        send_telegram_message(chat_id, buffer.strip())
            except Exception as e:
                logger.exception("Error processing message: %s", e)
                send_telegram_message(chat_id, "Maaf, berlaku ralat semasa memproses permintaan. Sila cuba lagi kemudian.")
        background.add_task(process_and_reply, chat_id, text)
    return {"ok": True}
