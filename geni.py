import os
import subprocess
import glob
import threading
import time
import sys
import psycopg2
from pgvector.psycopg2 import register_vector
from google import genai
from dotenv import load_dotenv

# --- Initialisation ---
load_dotenv()

# --- Configuration et Chemins ---
GLOG_PATH = os.path.expanduser("~/.local/bin/glog.py")
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}
PYTHON_BIN = sys.executable

# --- Configuration de l'auto-complétion ---
try:
    import readline


    def completer(text, state):
        options = glob.glob(text + '*')
        if state < len(options):
            option = options[state]
            return option + os.sep if os.path.isdir(option) else option
        return None


    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(' \t\n;')
except ImportError:
    readline = None


# --- Fonctions Utilitaires ---

def find_file_recursive(filename):
    exclude_dirs = {'.git', 'vendor', 'node_modules', 'var', 'cache'}
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        if filename in files:
            return os.path.join(root, filename)
    return None


def extract_single_range(lines, r_string, file_path):
    try:
        start, end = map(int, r_string.split('-'))
        part = lines[start - 1:end]
        return f"--- {file_path} (Lignes {r_string}) ---\n" + "".join(part)
    except Exception as e:
        return f"  [!] Erreur sur la plage {r_string}: {e}"


def spinner_task(stop_event):
    chars = ['|', '/', '-', '\\']
    idx = 0
    while not stop_event.is_set():
        print(f"\r[Gemini réfléchit...] {chars[idx % len(chars)]}", end="", flush=True)
        idx += 1
        time.sleep(0.1)
    print("\r" + " " * 30 + "\r", end="", flush=True)


def get_repo_map():
    """Génère ou récupère la carte du projet via Aider."""
    try:
        # On demande à aider de générer la map (silencieusement)
        result = subprocess.run(
            ["aider", "--show-repo-map"],
            capture_output=True, text=True, encoding='utf-8'
        )
        return result.stdout
    except subprocess.SubprocessError:
        return "Impossible de générer le repo-map."


# --- Fonction Principale ---

def run():
    print("=== ASSISTANT GEMINI (Fichiers + Mémoire + YAML) ===")

    main_prompt = input("\nVotre question : ").strip()
    if not main_prompt:
        print("Erreur : Question obligatoire.")
        return

    context_blocks = []
    while True:
        f_input = input("\nFichier (TAB / Entrée pour terminer) : ").strip()
        if not f_input:
            break

        f_path = f_input.replace('"', '').replace("'", "")
        if not os.path.exists(f_path):
            found = find_file_recursive(f_path)
            if found:
                f_path = found
            else:
                print(f"  [!] Fichier non trouvé.")
                continue

        if os.path.isdir(f_path):
            print(f"  [!] C'est un dossier. Choisissez un fichier.")
            continue

        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            file_parts = []
            while True:
                r_input = input(
                    f"  Plage pour '{os.path.basename(f_path)}' (ex: 10-50 / Entrée pour tout prendre) : ").strip()
                if not r_input:
                    if not file_parts:
                        context_blocks.append(f"--- FICHIER COMPLET : {f_path} ---\n" + "".join(lines))
                        print(f"  [+] Fichier complet ajouté.")
                    break

                part = extract_single_range(lines, r_input, f_path)
                file_parts.append(part)
                print(f"  [+] Plage {r_input} ajoutée.")

            if file_parts:
                context_blocks.append("\n\n[...]\n\n".join(file_parts))

        except Exception as e:
            print(f"  [!] Erreur : {e}")

    # --- Récupération du repo_map d'Aider ---
    repo_map = get_repo_map()

    # --- Récupération Mémoires ---
    summary_content = "Aucun résumé disponible."
    if os.path.exists("resume_contexte.yaml"):
        with open("resume_contexte.yaml", "r", encoding='utf-8') as f:
            summary_content = f.read()

    print("\n🔍 Consultation de la mémoire à long terme...")
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

        res = client.models.embed_content(
            model="models/gemini-embedding-001",
            contents=main_prompt,
            config={'output_dimensionality': 768}
        )
        embedding = res.embeddings[0].values

        conn = psycopg2.connect(**DB_CONFIG)
        register_vector(conn)
        cur = conn.cursor()

        # On récupère les 3 meilleurs souvenirs
        cur.execute("SELECT content FROM chat_history ORDER BY embedding <=> %s::vector LIMIT 3", (embedding,))
        rows = cur.fetchall()
        context_vectoriel = "\n".join([f"--- Souvenir {i + 1} ---\n{r[0]}" for i, r in enumerate(rows)])
        cur.close()
        conn.close()
    except Exception as e:
        context_vectoriel = f"Erreur mémoire : {e}"

    # --- Construction du Prompt Final ---
    files_context_string = "\n\n".join(context_blocks)
    full_prompt = f"""
[STRUCTURE_DU_PROJET]
{repo_map}
[/STRUCTURE_DU_PROJET]

[CONTEXTE_STRUCTUREL_YAML]
{summary_content}
[/CONTEXTE_STRUCTUREL_YAML]

[CONTEXTE_FICHIERS]
{files_context_string}
[/CONTEXTE_FICHIERS]

[CONTEXTE_VECTORIEL]
{context_vectoriel}
[/CONTEXTE_VECTORIEL]

QUESTION_UTILISATEUR : {main_prompt}"""

    # --- Envoi STDIN ---
    print("\n🚀 Envoi à Gemini...")
    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(target=spinner_task, args=(stop_spinner,))

    try:
        spinner_thread.start()
        # On passe full_prompt via stdin au script glog.py
        subprocess.run(
            [PYTHON_BIN, GLOG_PATH, main_prompt],
            input=full_prompt,
            text=True,
            encoding='utf-8'
        )
        stop_spinner.set()
        spinner_thread.join()
    except Exception as e:
        stop_spinner.set()
        print(f"\nErreur : {e}")


if __name__ == "__main__":
    run()
