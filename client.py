import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv
import requests
import json

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
URL = "https://openrouter.webtrader.fr/relay"

cipher = Fernet(ENCRYPTION_KEY)

# Le payload à envoyer à OpenRouter
payload = {
    "model": "google/gemini-2.0-flash-001",
    "messages": [{"role": "user", "content": "Bonjour, est-ce que tu me reçois ?"}]
}

# Préparation du dictionnaire incluant le token
data_to_send = {
    "internal_token": SECRET_TOKEN,
    "payload": payload
}

# Chiffrement
encrypted_data = cipher.encrypt(json.dumps(data_to_send).encode())

# Envoi de la requête POST
response = requests.post(URL, data=encrypted_data)

print(f"Statut : {response.status_code}")
print(f"Réponse : {response.text}")
