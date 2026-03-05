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
import argparse
import io

# Force Windows à parler UTF-8 au niveau du système
if os.name == 'nt':
    os.system('chcp 65001 > nul')

# Force l'UTF-8 pour les pipes Windows Terminal
if sys.platform == "win32":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

# --- INITIALISATION ---
load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY").encode()
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
RELAY_URL = os.getenv("RELAY_URL")

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

# 1. On crée l'objet console au niveau GLOBAL. Par défaut, il écrit sur stdout
console = Console()


# --- FONCTIONS DE SERVICE ---

def get_project_id():
    """Identifie le projet par le nom du dossier courant."""
    return os.path.basename(os.getcwd())


def index_interaction(full_text, project_id):
    """Calcule le hash, l'embedding et insère dans Postgres avec l'ID du projet."""
    # Nettoyage préventif pour s'assurer que c'est de l'UTF-8 pur
    if isinstance(full_text, bytes):
        full_text = full_text.decode('utf-8', errors='replace')
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
                if cur.fetchone():
                    return

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
                        "INSERT INTO chat_history (content, content_hash, embedding, project_id) "
                        "VALUES (%s, %s, %s, %s)",
                        (full_text, content_hash, res.embeddings[0].values, project_id)
                    )
                    console.print(f"[bold green]✔[/bold green] [bold cyan]Mémoire vectorielle synchronisée "
                                  f"({project_id}).[/bold cyan]")
                except MemoryError as e:
                    console.print(f"[bold red]⚠️ Mémoire insuffisante pour l'embedding : {e}[/bold red]")
                    return
                except Exception as e:
                    console.print(f"[bold red]⚠️ Erreur lors de la génération de l'embedding : {e}[/bold red]")
                    return

    except Exception as e:
        console.print(f"[bold red]⚠️ Note: Échec de l'indexation vectorielle ({str(e)[:100]})[/bold red]")


def update_global_summary(user_query, ai_response, project_id):
    """Consolide la mémoire normative YAML avec basculement intelligent."""
    # Petite pause pour éviter le Rate Limit (429) juste après la réponse principale
    time.sleep(1)

    # Pile de modèles pour la consolidation
    archive_models = [
        "google/gemini-2.0-flash-001",
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
                "temperature": 0.1,
                "max_tokens": 2048,  # Limite suffisante pour un résumé
                "project_id": project_id  # Injection dans le payload pour le relais
            }

            data_to_send = {"internal_token": SECRET_TOKEN, "payload": payload}
            encrypted_data = cipher.encrypt(json.dumps(data_to_send).encode())

            # Appel via relais
            response = requests.post(RELAY_URL, data=encrypted_data)

            if response.status_code == 200:
                resp_json = response.json()
                if 'choices' in resp_json:
                    raw = resp_json['choices'][0]['message']['content']
                    clean_yaml = re.sub(r'```yaml|```', '', raw).strip()

                    with open(summary_file, 'w', encoding='utf-8') as f:
                        f.write(clean_yaml)
                    console.print(
                        "[bold green]✔[/bold green] [bold cyan]Mémoire normative consolidée (via Relais).[/bold cyan]")
                    return
                else:
                    # Affiche l'erreur d'OpenRouter
                    print(f"Erreur OpenRouter : {json.dumps(resp_json, indent=2)}")
                    raise KeyError("Clé 'choices' manquante dans la réponse du relais")
        except Exception as e:
            # Plus de transparence sur l'échec de consolidation
            err_msg = str(e)
            console.print(f"[bold red]⚠️ Échec consolidation avec {model} : {err_msg[:60]}[/bold red]...")
            continue


def apply_gemini_edits(ai_response):
    """Parse et applique les blocs FILE/SEARCH/REPLACE/END de la réponse."""
    pattern = r"FILE:\s*[`']?(.*?)`?\s*SEARCH:\s*(.*?)\s*REPLACE:\s*(.*?)\s*END"
    matches = re.findall(pattern, ai_response, re.DOTALL)

    if not matches:
        return False

    console.print(Rule("[bold yellow]Application des modifications[/bold yellow]"))

    for file_path, search_text, replace_text in matches:
        file_path = file_path.strip().replace('`', '').replace("'", "")

        # Nettoyage des balises markdown
        def clean(t):
            t = t.strip()
            t = re.sub(r'^```[a-z]*\n', '', t, flags=re.IGNORECASE)
            return re.sub(r'\n```$', '', t).strip('`').strip()

        search_text = clean(search_text)
        replace_text = clean(replace_text)

        # Gestion Création vs Modification
        if "NEW_FILE" in search_text or not os.path.exists(file_path):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(replace_text)
            console.print(f"[bold green]🆕 Créé :[/bold green] {file_path}")
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if search_text in content:
                new_content = content.replace(search_text, replace_text)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                console.print(f"[bold green]✅ Modifié :[/bold green] {file_path}")
            else:
                console.print(f"[bold red]❌ Non trouvé :[/bold red] {file_path} (le bloc SEARCH ne correspond pas)")
    return True


# --- LOGIQUE PRINCIPALE ---

def run():
    # 1. GESTION DES ARGUMENTS
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="*", help="La question pour l'IA")
    parser.add_argument("--mode", choices=["CHAT", "PLAN"], default="CHAT", help="Mode d'exécution")
    parser.add_argument("--yes", action="store_true", help="Approuver automatiquement les modifs")
    args = parser.parse_args()

    current_user_question = " ".join(args.question)
    is_plan_mode = (args.mode == "PLAN")

    # 2. Configuration de la console selon le mode. On indique qu'on va modifier l'objet global
    global console

    # On utilise stderr pour les logs afin de laisser stdout au JSON en mode PLAN
    console = Console(stderr=True) if is_plan_mode else Console()

    # 2. Collecte des entrées (Arguments + Pipe) et détection du projet
    project_id = get_project_id()
    context_data = sys.stdin.read() if not sys.stdin.isatty() else ""

    if not current_user_question and not context_data:
        console.print("[bold red]❌ Erreur : Aucun contenu fourni.[/bold red]")
        return

    # 3. Exécution d'ask.py avec un indicateur visuel global
    console.print(Rule("[bold green]Requête IA[/bold green]"))

    try:
        result = subprocess.run(
            [PYTHON_BIN, ASK_SCRIPT, current_user_question],
            input=context_data.encode('utf-8'),  # On envoie des bytes
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # <--- ON PASSE EN BYTES pour éviter le crash du thread
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )

        # On décode manuellement avec "replace" pour les caractères 0xe8/0xea
        ai_response = result.stdout.decode('utf-8', errors='replace').strip()
        err_response = result.stderr.decode('utf-8', errors='replace').strip()

        if result.returncode != 0:
            console.print(f"\n[bold red]🛑 Erreur fatale (Code {result.returncode})[/bold red]")
            console.print(f"[yellow]STDERR:[/yellow] {err_response}")
            return

        if not ai_response:
            console.print("⚠️ Réponse vide reçue de l'IA.")
            return

        # 4. Rendu de la réponse
        if is_plan_mode:
            # On cherche le JSON dans la réponse au cas où l'IA aurait bavardé
            match = re.search(r'(\{.*\})', ai_response, re.DOTALL)
            clean_json = match.group(1) if match else ai_response

            console.print("[dim][Relais] Mode PLAN : Envoi JSON sur stdout...[/dim]")
            sys.stdout.write(clean_json)
            sys.stdout.flush()
        else:
            console.print("\n")
            render_md = Markdown(ai_response)
            console.print(
                Panel(render_md, title="[bold green]Analyse[/bold green]", border_style="green", expand=False))

        # 5. Écriture des fichiers de sortie et post-traitement
        console.print(Rule("[bold green]Post-traitement[/bold green]"))

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"\n{'=' * 50}\nDATE   : {timestamp}\nPROMPT : {current_user_question}\n{'-' * 50}\n"
        full_entry = f"{header}{ai_response}\n"

        try:
            with open('dernier_plan.md', 'w', encoding='utf-8') as p:
                p.write(ai_response)

            with open('historique_global.md', 'a', encoding='utf-8') as h:
                h.write(full_entry)
        except OSError as e:
            console.print(f"[bold red]❌ Erreur disque : {e}[/bold red]")
            return

        # 6. APPLICATION DU PLAN
        if "SEARCH:" in ai_response and "REPLACE:" in ai_response:
            console.print("\n")
            confirm_panel = Panel(
                "[bold yellow]L'IA a généré des instructions de modification de fichiers.[/bold yellow]\n"
                "Voulez-vous appliquer ces changements chirurgicaux maintenant ?",
                title="[bold red]🛠 ACTION REQUISE[/bold red]",
                border_style="yellow",
                padding=(1, 2)
            )
            console.print(confirm_panel)

            # Gestion de l'input même si stdin est utilisé par un pipe
            try:
                # Sous Windows, on utilise 'CON' pour lire le terminal directement, '/dev/tty' sous Linux/Mac.
                term_path = 'CON' if os.name == 'nt' else '/dev/tty'
                with open(term_path, 'r') as f:
                    console.print("👉 Appliquer ? (y/N) [default: n] : ", end="")
                    choice = f.readline().strip().lower()
            except (OSError, IOError):
                # Fallback si l'ouverture du terminal échoue
                try:
                    choice = input("👉 Appliquer ? (y/N) [default: n] : ").strip().lower()
                except EOFError:
                    choice = 'n'

            confirm = choice if choice else 'n'

            if confirm == 'y':
                apply_gemini_edits(ai_response)
            else:
                console.print(
                    "[yellow]⏩ Application ignorée. Les modifications sont conservées dans 'dernier_plan.md'.[/yellow]")

        # 7. Lancement des indexations et résumés
        index_interaction(full_entry, project_id)
        update_global_summary(current_user_question, ai_response, project_id)

        console.print(f"[bold green]✔[/bold green] [bold cyan]Workflow terminé avec succès [{project_id}].[/bold cyan]")

    except Exception as e:
        console.print(f"[bold red]❌ Erreur système :[/bold red] {e}")


if __name__ == "__main__":
    run()
