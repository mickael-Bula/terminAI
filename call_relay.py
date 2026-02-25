import os
import sys
import re
import time
from cryptography.fernet import Fernet
import requests
import json
from dotenv import load_dotenv
from rich.console import Console

# --- Configuration de l'environnement ---
load_dotenv()

# Force le chemin vers les bibliothèques Laragon si nécessaire
site_packages = r"c:\laragon\bin\python\python-3.10\lib\site-packages"
if site_packages not in sys.path:
    sys.path.append(site_packages)

# On utilise stderr pour que les logs ne soient pas capturés dans la réponse finale
console = Console(stderr=True)

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY").encode()
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
RELAY_URL = os.getenv("RELAY_URL")
LOCAL_BIN = os.getenv("LOCAL_BIN")


def ask_question(user_prompt):
    cipher = Fernet(ENCRYPTION_KEY)

    # Pile de modèles
    models = [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-pro-exp-02-05:free",
        "meta-llama/llama-3.3-70b-instruct:free"
    ]

    with console.status("[bold blue]Initialisation via Relais...[/bold blue]", spinner="dots") as status:
        for model_name in models:
            status.update(f"[bold blue]Réflexion avec {model_name}...[/bold blue]")

            # Construire le payload comme attendu par relay.py
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": user_prompt}]
            }

            data_to_send = {
                "internal_token": SECRET_TOKEN,
                "payload": payload
            }

            try:
                # Chiffrement
                encrypted_data = cipher.encrypt(json.dumps(data_to_send).encode())

                # Requête vers le relais
                response = requests.post(RELAY_URL, data=encrypted_data)

                if response.status_code != 200:
                    raise Exception(f"Erreur API Relais: {response.status_code} - {response.text}")

                # Traitement de la réponse
                resp_json = response.json()
                raw_content = resp_json['choices'][0]['message']['content']
                clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

                return clean_content

            except Exception as e:
                console.print(f"[bold red]⚠️  ÉCHEC : {model_name}[/bold red]")
                console.print(f"[bold red]   CAUSE : {str(e)[:50]}[/bold red]")
                time.sleep(0.3)
                continue

        return None


# --- Gestion des entrées et du workflow ---

def ask():
    # Lecture du prompt système (si présent)
    system_prompt_path = fr"{LOCAL_BIN}\prompt_system.txt"
    system_content = ""
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            system_content = f.read().strip()

    # Capture du flux (Pipe) ou des arguments
    pipe_content = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    user_query = " ".join(sys.argv[1:]).strip()

    # Assemblage final
    parts = []
    if system_content:
        parts.append(f"### SYSTEM INSTRUCTIONS ###\n{system_content}")
    if pipe_content:
        parts.append(f"### CONTEXT ###\n{pipe_content}")
    if user_query:
        parts.append(f"### USER QUERY ###\n{user_query}")

    prompt_final = "\n\n---\n\n".join(parts)

    if not prompt_final.strip():
        console.print("Usage: glog 'votre question' ou cat file | glog")
        return

    try:
        response = ask_question(prompt_final)
        # On utilise le print() natif, glog se chargeant d'ajouter les styles.
        if response:
            print(response)
    except Exception as e:
        console.print(f"Erreur fatale : {e}")
        sys.exit(1)


if __name__ == "__main__":
    ask()
