import sys
import subprocess
import datetime
import os
import hashlib
import re
import time
import psycopg2
from pgvector.psycopg2 import register_vector
from google import genai
from openai import OpenAI
from dotenv import load_dotenv

# --- INITIALISATION ---
load_dotenv()

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
ASK_SCRIPT = os.path.join(LOCAL_BIN, 'ask.py')
PYTHON_BIN = os.environ.get('PYTHON_BIN', 'python')


# --- FONCTIONS DE SERVICE ---

def index_interaction(full_text):
    """Calcule le hash, l'embedding et insère dans Postgres."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key: return

        client = genai.Client(api_key=api_key)
        content_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

        with psycopg2.connect(**DB_CONFIG) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                # Vérification unicité
                cur.execute("SELECT id FROM chat_history WHERE content_hash = %s", (content_hash,))
                if cur.fetchone(): return

                # Génération Embedding
                res = client.models.embed_content(
                    model="models/gemini-embedding-001",
                    contents=full_text,
                    config={'output_dimensionality': 768}
                )

                cur.execute(
                    "INSERT INTO chat_history (content, content_hash, embedding) VALUES (%s, %s, %s)",
                    (full_text, content_hash, res.embeddings[0].values)
                )
        print("✅ Mémoire vectorielle synchronisée.")
    except Exception as e:
        print(f"⚠️ Note: Échec de l'indexation vectorielle ({str(e)[:100]})", file=sys.stderr)


def update_global_summary(user_query, ai_response):
    """Consolide la mémoire normative YAML avec basculement intelligent."""
    # Petite pause pour éviter le Rate Limit (429) juste après la réponse principale
    time.sleep(1)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    # Pile de modèles pour la consolidation
    archive_models = [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-flash-lite-001",
        "qwen/qwen-2.5-72b-instruct:free",
        "openrouter/auto"
    ]

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
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": "Tu es un archiviste YAML."},
                          {"role": "user", "content": prompt_consolidation}],
                temperature=0.1
            )
            raw = response.choices[0].message.content
            clean_yaml = re.sub(r'```yaml|```', '', raw).strip()

            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(clean_yaml)
            print("📊 Mémoire normative (YAML) consolidée.")
            return
        except Exception as e:
            # Plus de transparence sur l'échec de consolidation
            err_msg = str(e)
            print(f"⚠️ Échec consolidation avec {model} : {err_msg[:60]}...", file=sys.stderr)
            continue


# --- LOGIQUE PRINCIPALE ---

def run():
    # 1. Collecte des entrées (Arguments + Pipe)
    user_question = " ".join(sys.argv[1:])
    context_data = sys.stdin.read() if not sys.stdin.isatty() else ""

    if not user_question and not context_data:
        print("❌ Erreur : Aucun contenu fourni.")
        return

    # 2. Exécution de ask.py
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
            print(f"\n[ABORT] L'IA a rencontré une erreur fatale.", file=sys.stderr)
            return

        ai_response = result.stdout.strip()
        if not ai_response:
            print("⚠️ Réponse vide reçue de l'IA.")
            return

        # 3. Écriture des fichiers de sortie
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"\n{'=' * 50}\nDATE   : {timestamp}\nPROMPT : {user_question}\n{'-' * 50}\n"
        full_entry = f"{header}{ai_response}\n"

        try:
            with open('dernier_plan.md', 'w', encoding='utf-8') as p:
                p.write(ai_response)

            with open('historique_global.md', 'a', encoding='utf-8') as h:
                h.write(full_entry)
        except OSError as e:
            print(f"❌ Erreur disque : {e}", file=sys.stderr)
            return

        # 4. Affichage final et tâches de fond
        print(ai_response)

        # Lancement des indexations et résumés
        index_interaction(full_entry)
        update_global_summary(user_question, ai_response)

    except Exception as e:
        print(f"❌ Erreur système : {e}", file=sys.stderr)


if __name__ == "__main__":
    run()
