import os
import sys
import re
import time
import threading
import itertools
from openai import OpenAI
from dotenv import load_dotenv

# --- Configuration de l'environnement ---
load_dotenv()

# Force le chemin vers les bibliothèques Laragon si nécessaire
site_packages = r"c:\laragon\bin\python\python-3.10\lib\site-packages"
if site_packages not in sys.path:
    sys.path.append(site_packages)


# --- Logique du Spinner ---

def spinner_animation(stop_event, model_name):
    """Anime un spinner sur stderr sans polluer stdout."""
    chars = itertools.cycle(['|', '/', '-', '\\'])
    for char in chars:
        if stop_event.is_set():
            break
        # On écrit sur la même ligne (\r). L'espace à la fin permet d'effacer les restes de noms de modèles plus longs.
        sys.stderr.write(f"\r⏳ [{char}] Réflexion avec {model_name}...")
        sys.stderr.flush()
        time.sleep(0.1)

    # Nettoyage final de la ligne avant de rendre la main
    sys.stderr.write("\r" + " " * 80 + "\r")
    sys.stderr.flush()


# --- Cœur du système de questionnement ---

def ask_question(user_prompt):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    # Pile de modèles (Failover)
    models = [
        "deepseek/deepseek-r1",
        "google/gemini-2.0-pro-exp-02-05:free",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/auto"
    ]

    for model_name in models:
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(target=spinner_animation, args=(stop_spinner, model_name))

        try:
            spinner_thread.start()

            # Appel API
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.7
            )

            # --- Succès ---
            stop_spinner.set()
            spinner_thread.join()

            raw_content = response.choices[0].message.content
            # Filtrage du bloc de réflexion DeepSeek
            clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

            print(f"✅ Réponse générée par : {model_name}", file=sys.stderr)
            return clean_content

        except Exception as e:
            # --- Erreur rencontrée ---
            stop_spinner.set()
            spinner_thread.join()  # On attend que le spinner s'arrête proprement

            error_msg = str(e)
            passable_errors = ["429", "404", "402", "NOT_FOUND", "500", "503", "CREDITS", "BALANCE"]

            # Si l'erreur est dans notre liste de secours
            if any(err in error_msg.upper() for err in passable_errors):
                print(f"⚠️  MODÈLE KO : {model_name}", file=sys.stderr)
                print(f"   CAUSE : {error_msg[:80]}...", file=sys.stderr)
                print(f"🔄 Passage au modèle suivant...\n", file=sys.stderr)
                time.sleep(0.3)  # Petit délai pour laisser le temps de lire l'erreur
                continue

            # Si l'erreur est vraiment critique (ex: Clé API invalide)
            print(f"❌ Erreur critique avec {model_name}: {e}", file=sys.stderr)
            raise e


# --- Gestion des entrées et du workflow ---

def ask():
    # Lecture du prompt système (si présent)
    system_prompt_path = r"C:\Users\bulam\.local\bin\prompt_system.txt"
    system_content = ""
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            system_content = f.read().strip()

    # Capture du flux (Pipe) ou des arguments
    pipe_content = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    user_query = " ".join(sys.argv[1:]).strip()

    # Assemblage final
    parts = []
    if system_content: parts.append(f"### SYSTEM INSTRUCTIONS ###\n{system_content}")
    if pipe_content:   parts.append(f"### CONTEXT ###\n{pipe_content}")
    if user_query:     parts.append(f"### USER QUERY ###\n{user_query}")

    prompt_final = "\n\n---\n\n".join(parts)

    if not prompt_final.strip():
        print("Usage: glog 'votre question' ou cat file | glog", file=sys.stderr)
        return

    try:
        response = ask_question(prompt_final)
        # On envoie uniquement la réponse IA sur stdout pour capture par glog.py
        if response:
            print(response)
    except Exception as e:
        print(f"Erreur fatale : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    ask()
