import httpx
from fastapi import FastAPI, Request
from cryptography.fernet import Fernet
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
cipher = Fernet(os.getenv("ENCRYPTION_KEY").encode())
RELAY_URL = "https://openrouter.webtrader.fr/relay"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")


@app.post("/{path:path}")
async def handle_proxy(request: Request, path: str):
    # 1. Recevoir le JSON d'Aider
    payload = await request.json()

    # 2. Préparer l'enveloppe sécurisée
    data_to_encrypt = {
        "internal_token": SECRET_TOKEN,
        "payload": payload
    }

    # 3. Chiffrer
    encrypted_data = cipher.encrypt(str(data_to_encrypt).replace("'", '"').encode())

    # 4. Envoyer au LXC (via HTTPS standard, sans headers suspects)
    async with httpx.AsyncClient() as client:
        resp = await client.post(RELAY_URL, content=encrypted_data)
        return resp.json()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
