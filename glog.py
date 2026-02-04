import sys
import subprocess
import datetime
import os
import hashlib
import psycopg2
from pgvector.psycopg2 import register_vector
from google import genai


def index_interaction(full_text):
    """Calcule le hash, l'embedding et insère dans Postgres (Port 5433)."""
    try:
        # Configuration de la base de données
        db_config = "host=localhost port=5433 dbname=gemini_history user=bulam password=your_secure_password"
        api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            return  # Pas d'API key, on ignore l'indexation

        client = genai.Client(api_key=api_key)

        # 1. Calcul de l'empreinte unique (Hash)
        content_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

        # 2. Connexion Postgres
        conn = psycopg2.connect(db_config)
        register_vector(conn)
        cur = conn.cursor()

        # 3. Vérification si déjà indexé
        cur.execute("SELECT id FROM chat_history WHERE content_hash = %s", (content_hash,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return

        # 4. Génération de l'Embedding
        res = client.models.embed_content(model="text-embedding-004", contents=full_text)
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


def run():
    # 1. Vérification et création du dossier de scripts si nécessaire
    # On récupère le chemin depuis l'environnement ou on utilise celui par défaut
    local_bin = os.environ.get('LOCAL_BIN', r'C:\Users\bulam\.local\bin')
    if not os.path.exists(local_bin):
        try:
            os.makedirs(local_bin, exist_ok=True)
        except Exception as e:
            print(f"Erreur lors de la création du dossier {local_bin} : {e}")

    # 2. Récupérer le prompt passé en argument
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

    except Exception as e:
        print(f"Une erreur système est survenue : {e}")


if __name__ == "__main__":
    run()
