import sys
import subprocess
import datetime
import os
import hashlib
import re
import time
import psycopg2
from google.genai import types
from pgvector.psycopg2 import register_vector
from google import genai
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule
from cryptography.fernet import Fernet
import requests
import json

# --- INITIALISATION ---
load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY").encode()
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
RELAY_URL = os.getenv("RELAY_URL")

# On utilise stderr pour que les logs ne soient pas capturés dans la réponse finale
console = Console(stderr=True)

# Configuration DB
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

# Configuration Chemins
LOCAL_BIN = os.environ.get('LOCAL_BIN', os.path.expanduser(r'~\.local\bin'))
ASK_SCRIPT = os.path.join(LOCAL_BIN, 'call_relay.py')
PYTHON_BIN = os.environ.get('PYTHON_BIN', 'python')


# --- FONCTIONS DE SERVICE ---

def index_interaction(full_text):
    """Calcule le hash, l'embedding et insère dans Postgres."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return

        client = genai.Client(api_key=api_key)
        content_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

        with psycopg2.connect(**DB_CONFIG) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                # Vérification unicité
                cur.execute("SELECT id FROM chat_history WHERE content_hash = %s", (content_hash,))
                if cur.fetchone(): return

                # Génération Embedding
                try:
                    res = client.models.embed_content(
                        model="models/gemini-embedding-001",
                        contents=full_text,
                        config=types.EmbedContentConfig(
                            output_dimensionality=768
                        )
                    )

                    cur.execute(
                        "INSERT INTO chat_history (content, content_hash, embedding) VALUES (%s, %s, %s)",
                        (full_text, content_hash, res.embeddings[0].values)
                    )
                    console.print("[bold green]✔[/bold green] [bold cyan]Mémoire vectorielle synchronisée.[/bold cyan]")
                except MemoryError as e:
                    console.print(f"[bold red]⚠️ Mémoire insuffisante pour l'embedding : {e}[/bold red]")
                    return
                except Exception as e:
                    console.print(f"[bold red]⚠️ Erreur lors de la génération de l'embedding : {e}[/bold red]")
                    return

    except Exception as e:
        console.print(f"[bold red]⚠️ Note: Échec de l'indexation vectorielle ({str(e)[:100]})[/bold red]")


def update_global_summary(user_query, ai_response):
    """Consolide la mémoire normative YAML avec basculement intelligent."""
    # Petite pause pour éviter le Rate Limit (429) juste après la réponse principale
    time.sleep(1)

    # Pile de modèles pour la consolidation
    archive_models = [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-pro-exp-02-05:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "openrouter/auto"
    ]

    cipher = Fernet(ENCRYPTION_KEY)

    summary_file = 'resume_contexte.yaml'

    if os.path.exists(summary_file):
        with open(summary_file, 'r', encoding='utf-8') as f:
            old_summary = f.read()
    else:
        old_summary = "summary: {objective: 'Initialisation', decisions: {confirmed: [], rejected: []}}"

    prompt_consolidation = f"""
Tu dois consolider la mémoire normative utilisée pour la conversation.

OBJECTIF
- Produire un résumé cohérent et stable
- Réduire le bruit et les informations redondantes
- Respecter les décisions et contraintes établies
- Préparer la mémoire pour les prochaines interactions

RÈGLES STRICTES
- Tu peux réécrire la mémoire complète, mais uniquement pour la **clarté et la cohérence**
- Ne supprime jamais une décision confirmée ou rejetée sans raison explicite
- Les hypothèses non validées doivent rester dans open_questions
- Les contraintes doivent être conservées telles quelles
- Ne jamais inclure de contexte vectoriel ou de texte libre
- Limiter chaque item à une phrase courte et claire
- Le résumé final doit être concis (≤ 50 lignes si possible)

FORMAT DE SORTIE
- YAML uniquement
- Racine : summary
- Champs autorisés :
  - objective
  - constraints
  - decisions:
      confirmed
      rejected
  - open_questions
  - next_actions
- Aucun texte hors YAML

MÉMOIRE ACTUELLE :
{old_summary}

DERNIÈRE INTERACTION :
Utilisateur : {user_query}
IA : {ai_response[:2000]}
"""

    for model in archive_models:
        try:
            # Construction du payload pour le relais
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Tu es un archiviste YAML."},
                    {"role": "user", "content": prompt_consolidation}
                ],
                "temperature": 0.1
            }

            data_to_send = {"internal_token": SECRET_TOKEN, "payload": payload}
            encrypted_data = cipher.encrypt(json.dumps(data_to_send).encode())

            # Appel via relais
            response = requests.post(RELAY_URL, data=encrypted_data)

            if response.status_code == 200:
                raw = response.json()['choices'][0]['message']['content']
                clean_yaml = re.sub(r'```yaml|```', '', raw).strip()

                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(clean_yaml)
                console.print(
                    "[bold green]✔[/bold green] [bold cyan]Mémoire normative consolidée (via Relais).[/bold cyan]")
                return
        except Exception as e:
            # Plus de transparence sur l'échec de consolidation
            err_msg = str(e)
            console.print(f"[bold red]⚠️ Échec consolidation avec {model} : {err_msg[:60]}[/bold red]...")
            continue


# --- LOGIQUE PRINCIPALE ---

def run():
    # 1. Collecte des entrées (Arguments + Pipe)
    user_question = " ".join(sys.argv[1:])
    context_data = sys.stdin.read() if not sys.stdin.isatty() else ""

    if not user_question and not context_data:
        console.print("[bold red]❌ Erreur :[/bold red] Aucun contenu fourni.[/bold red")
        return

    # 2. Exécution d'ask.py avec un indicateur visuel global
    console.print(Rule("[bold green]Requête IA[/bold green]"))

    try:
        result = subprocess.run(
            [PYTHON_BIN, ASK_SCRIPT, user_question],
            input=context_data,
            stdout=subprocess.PIPE,
            stderr=None,  # Stream direct du spinner et du debug de ask.py
            text=True,
            encoding='utf-8'
        )

        if result.returncode != 0:
            console.print(f"\n[bold red]🛑 Erreur fatale (Code {result.returncode})[/bold red]")
            console.print(f"DEBUG STDOUT: {result.stdout}")
            console.print(f"DEBUG STDERR: {result.stderr}")
            return

        ai_response = result.stdout.strip()
        if not ai_response:
            print("⚠️ Réponse vide reçue de l'IA.")
            return

        # 3. Rendu de la réponse en Markdown dans un Panel
        console.print("\n")
        render_md = Markdown(ai_response)
        console.print(
            Panel(render_md, title="[bold green]Analyse du Modèle[/bold green]", border_style="green", expand=False))

        # 4. Écriture des fichiers de sortie
        console.print(Rule("[bold green]Post-traitement[/bold green]"))

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"\n{'=' * 50}\nDATE   : {timestamp}\nPROMPT : {user_question}\n{'-' * 50}\n"
        full_entry = f"{header}{ai_response}\n"

        try:
            with open('dernier_plan.md', 'w', encoding='utf-8') as p:
                p.write(ai_response)

            with open('historique_global.md', 'a', encoding='utf-8') as h:
                h.write(full_entry)
        except OSError as e:
            console.print(f"[bold red]❌ Erreur disque : {e}[/bold red]")
            return

        # 5. Lancement des indexations et résumés
        index_interaction(full_entry)
        update_global_summary(user_question, ai_response)

        console.print("[bold green]✔[/bold green] [bold cyan]Workflow terminé avec succès.[/bold cyan]")

    except Exception as e:
        console.print(f"[bold red]❌ Erreur système :[/bold red] {e}")


if __name__ == "__main__":
    run()
