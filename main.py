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

# --- Background processor: does ALL sending & OpenAI calls ---
def process_and_reply(data: dict):
    try:
        # Basic validation
        if not isinstance(data, dict):
            logger.warning("Background: data not dict")
            return

        # Extract message
        message = data.get("message") or data.get("edited_message")
        if not message:
            logger.info("Background: no message field")
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            logger.warning("Background: no chat_id")
            return

        text = message.get("text", "") or message.get("caption", "")

        # 1) Send initial short ack (background) - keep small & robust
        try:
            send_telegram_message(chat_id, "Memproses permintaan anda... Sila tunggu sebentar.")
        except Exception:
            # Already logged inside send_telegram_message
            pass

        # 2) Build messages & call OpenAI
        try:
            messages = build_openai_messages(text)
            reply = call_openai(messages)
        except Exception as e:
            logger.exception("OpenAI call failed: %s", e)
            send_telegram_message(chat_id, "Maaf, berlaku ralat pada perkhidmatan AI. Sila cuba lagi kemudian.")
            return

        # 3) Send reply (split if terlalu panjang)
        try:
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
            logger.exception("Failed to send reply: %s", e)
            # final fallback
            try:
                send_telegram_message(chat_id, "Maaf, tidak dapat menghantar jawapan penuh. Sila hubungi pejabat SSM.")
            except Exception:
                pass

    except Exception as e:
        logger.exception("Unhandled error in background processor: %s", e)


@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """
    ACK cepat: parse JSON (safely), queue background task and RETURN 200 immediately.
    All heavy work is in process_and_reply (background).
    """
    try:
        data = await request.json()
    except Exception as e:
        logger.exception("Invalid JSON from Telegram: %s", e)
        # Return 200 so Telegram stops retrying bad payloads
        return {"ok": True}

    # Log minimal keys to help debug later
    try:
        logger.info("Received webhook (background queued). keys=%s", list(data.keys()))
    except Exception:
        pass

    # Queue the heavy work to background
    try:
        background.add_task(process_and_reply, data)
    except Exception as e:
        logger.exception("Failed to schedule background task: %s", e)
        # still return 200 to avoid Telegram retries
    return {"ok": True}
