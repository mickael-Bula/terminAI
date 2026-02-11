import sys
import subprocess
import datetime
import os
import hashlib
import re

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extensions import cursor
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Configuration de la base de données
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}


def index_interaction(full_text):
    """Calcule le hash, l'embedding et insère dans Postgres."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            return  # Pas d'API key, on ignore l'indexation

        client = genai.Client(api_key=api_key)

        # 1. Calcul de l'empreinte unique (Hash)
        content_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

        # 2. Connexion Postgres
        conn = psycopg2.connect(**DB_CONFIG)
        register_vector(conn)
        cur: cursor = conn.cursor()

        # 3. Vérification si déjà indexé
        cur.execute("SELECT id FROM chat_history WHERE content_hash = %s", (content_hash,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return

        # 4. Génération de l'Embedding
        res = client.models.embed_content(
            model="models/gemini-embedding-001",
            contents=full_text,
            config={'output_dimensionality': 768}
        )
        embedding = res.embeddings[0].values

        # 5. Insertion
        cur.execute(
            "INSERT INTO chat_history (content, content_hash, embedding) VALUES (%s, %s, %s)",
            (full_text, content_hash, embedding)
        )
        conn.commit()
        cur.close()
        conn.close()
        print("\n✅ Mémoire vectorielle synchronisée.")
    except Exception as e:
        # On affiche juste un avertissement pour ne pas bloquer le flux principal
        print(f"\n⚠️ Note: Échec de l'indexation vectorielle ({e})")


def update_global_summary(user_query_only, ai_response_only):
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    summary_file = 'resume_contexte.yaml'

    # On charge l'ancienne mémoire
    if os.path.exists(summary_file):
        with open(summary_file, 'r', encoding='utf-8') as f:
            old_summary = f.read()
    else:
        old_summary = "summary: {objective: 'Initialisation', decisions: {confirmed: [], rejected: []}}"

        # Au besoin, on tronque la réponse IA pour économiser les tokens et éviter le 429
        ai_response = ai_response_only[:4000] + "\n[...TRONQUÉ...]"
        ai_response_only = ai_response if len(ai_response_only) > 4000 else ai_response_only

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

MÉMOIRE ACTUELLE
{old_summary}

DERNIÈRE INTERACTION
Utilisateur : {user_query_only}
IA : {ai_response_only}

GÉNÈRE MAINTENANT LE RÉSUMÉ CONSOLIDÉ EN YAML.
    """

    try:
        response = client.models.generate_content(model='gemini-flash-latest', contents=prompt_consolidation)

        # Nettoyage si Gemini met des blocs ```yaml
        clean_yaml = response.text.replace('```yaml', '').replace('```', '').strip()

        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(clean_yaml)
        print("📊 Mémoire normative (YAML) consolidée.")

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            print("\n❌ QUOTA ÉPUISÉ POUR AUJOURD'HUI.")
            # Extraction du temps d'attente suggéré par Google
            wait_match = re.search(r"retry in ([\d\.]+)s", error_msg)
            if wait_match:
                print(f"💡 Google suggère d'attendre {wait_match.group(1)} secondes.")
            print("👉 Conseil : Change de clé API ou attends demain pour la consolidation.")
        else:
            print(f"❌ Erreur API : {e}")


def run():
    # 1. Vérification et création du dossier de scripts si nécessaire
    # On récupère le chemin depuis l'environnement ou on utilise celui par défaut
    local_bin = os.environ.get('LOCAL_BIN', r'C:\Users\bulam\.local\bin')
    if not os.path.exists(local_bin):
        try:
            os.makedirs(local_bin, exist_ok=True)
        except Exception as e:
            print(f"Erreur lors de la création du dossier {local_bin} : {e}")

    # 2. Récupérer le prompt
    if not sys.stdin.isatty():
        # Si on reçoit des données via un pipe (depuis glog_interactive)
        prompt = sys.stdin.read()
    else:
        # Si on appelle glog "en direct" dans le terminal
        prompt = " ".join(sys.argv[1:])

    if not prompt:
        print("Erreur : Aucun prompt fourni.")
        return

    # Configuration des chemins
    ask_script = os.environ.get('ASK_SCRIPT', os.path.join(local_bin, 'ask.py'))
    python_bin = os.environ.get('PYTHON_BIN', 'python')
    hist_file = 'historique_global.md'
    plan_file = 'dernier_plan.md'

    # 3. Préparer l'en-tête de l'historique
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    divider = "=" * 50
    header = f"\n{divider}\nDATE   : {timestamp}\nPROMPT : {prompt}\n{'-' * 50}\n"

    # 4. Exécuter ask.py et capturer la sortie
    # stdin=sys.stdin permet de transmettre le flux (ex : cat fichier | glog)
    try:
        result = subprocess.run(
            [python_bin, ask_script, prompt],
            capture_output=True,
            text=True,
            encoding='utf-8',
            stdin=sys.stdin
        )

        if result.returncode != 0:
            # On affiche l'erreur sur le flux d'erreur standard
            print(f"Erreur lors de l'exécution de Gemini :\n{result.stderr}", file=sys.stderr)
            return

        # 5. Écrire dans dernier_plan.md et historique_global.md
        content = result.stdout

        # Préparation du bloc complet pour l'historique et l'indexation
        full_entry = f"{header}{content}\n"

        # Écritures fichiers
        with open(plan_file, 'w', encoding='utf-8') as p:
            p.write(content)

        with open(hist_file, 'a', encoding='utf-8') as h:
            h.write(full_entry)

        # 6. Afficher le résultat dans le terminal
        print(content)

        # --- AUTO-INDEXATION VECTORIELLE ---
        index_interaction(full_entry)

        # --- GENERATION DU RESUME ---
        update_global_summary(prompt, content)

    except Exception as e:
        print(f"Une erreur système est survenue : {e}")


if __name__ == "__main__":
    run()
