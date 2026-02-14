import sys
import subprocess
import datetime
import os
import hashlib
import re
import openai

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extensions import cursor
from google import genai
from openai import OpenAI
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

        # 3. On s'assure que le contenu n'est pas déjà indexé.
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
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    # Pile de modèles pour l'ARCHIVAGE (Priorité au Gratuit)
    archive_models = [
        "mistralai/mistral-saba",
        "google/gemini-2.5-flash-lite-preview-09-2025",
        "qwen/qwen-2.5-72b-instruct:free",
        "openrouter/auto"
    ]

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
        for model in archive_models:
            try:
                # Envoi du prompt de consolidation YAML
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": "Tu es un archiviste YAML."},
                              {"role": "user", "content": prompt_consolidation}],
                    temperature=0.1  # On baisse la température pour plus de rigueur
                )

                # Récupère le contenu brut depuis la structure d'OpenAI
                raw_content = response.choices[0].message.content

                # Nettoyage si le modèle met des balises Markdown
                clean_yaml = raw_content.replace('```yaml', '').replace('```', '').strip()

                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(clean_yaml)
                print("📊 Mémoire normative (YAML) consolidée.")

                return
            except (openai.RateLimitError, openai.APIConnectionError,
                    openai.APITimeoutError, openai.APIError) as e:
                # Ici, on ne capture que les erreurs liées à l'API pour tenter le modèle suivant
                print(f"⚠️ Échec API avec {model} ({type(e).__name__}), tentative avec le suivant...")
                continue
            except OSError as e:
                # Erreur d'écriture de fichier (ex : permissions), inutile de changer de modèle IA
                print(f"❌ Erreur disque : {e}")
                break

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

    # 2. Récupérer le prompt (La question utilisateur)
    user_question = " ".join(sys.argv[1:])  # On distingue la question (argv) du contexte lourd (stdin).

    context_data = ""
    if not sys.stdin.isatty():
        context_data = sys.stdin.read()

    if not user_question and not context_data:
        print("Erreur : Aucun contenu fourni.")
        return

    # Configuration des chemins
    ask_script = os.environ.get('ASK_SCRIPT', os.path.join(local_bin, 'ask.py'))
    python_bin = os.environ.get('PYTHON_BIN', 'python')
    hist_file = 'historique_global.md'
    plan_file = 'dernier_plan.md'

    # 3. Préparer l'en-tête de l'historique
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    divider = "=" * 50
    header = f"\n{divider}\nDATE   : {timestamp}\nPROMPT : {user_question}\n{'-' * 50}\n"

    # 4. Exécuter ask.py et capturer la sortie
    # stdin=sys.stdin permet de transmettre le flux (ex : cat fichier | glog)
    try:
        result = subprocess.run(
            [python_bin, ask_script, user_question],
            input=context_data,  # On transmet le flux ici
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        if result.returncode != 0:
            # Si ask.py a fait un sys.exit(1), on s'arrête ici et on affiche l'erreur envoyée sur stderr.
            print(f"\n[ABORT] L'IA n'a pas pu répondre :\n{result.stderr}", file=sys.stderr)
            return

        # 5. Préparer le bloc complet EN MÉMOIRE d'abord (Write Once Logic)
        ai_response = result.stdout

        # On ne crée la chaîne finale QUE si on a bien reçu une réponse
        full_entry = f"{header}{ai_response}\n"

        # Écriture atomique : On ouvre, on écrit tout le bloc, on ferme immédiatement.
        try:
            # Mise à jour du dernier plan (écrase le précédent)
            with open(plan_file, 'w', encoding='utf-8') as p:
                p.write(ai_response)

            # Ajout à l'historique global (ajoute à la fin)
            # En écrivant 'full_entry' d'un coup, on évite d'avoir un header sans réponse
            with open(hist_file, 'a', encoding='utf-8') as h:
                h.write(full_entry)

        except OSError as e:
            print(f"❌ Erreur critique lors de l'écriture des fichiers : {e}")
            return  # On arrête tout si le disque est plein ou protégé

        # 6. Afficher le résultat dans le terminal
        print(ai_response)

        # --- AUTO-INDEXATION VECTORIELLE ---
        index_interaction(full_entry)

        # --- GENERATION DU RESUME ---
        update_global_summary(user_question, ai_response)

    except Exception as e:
        print(f"Une erreur système est survenue : {e}")


if __name__ == "__main__":
    run()
