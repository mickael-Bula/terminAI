import os
import subprocess
import datetime
import glob
import threading
import time

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


# --- Fonctions utilitaires ---

def find_file_recursive(filename):
    """Cherche un fichier dans les sous-dossiers (exclut les dossiers lourds)"""
    exclude_dirs = {'.git', 'vendor', 'node_modules', 'var', 'cache'}
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        if filename in files:
            return os.path.join(root, filename)
    return None


def spinner_task(stop_event):
    """Animation de chargement compatible Windows/Cmder"""
    chars = ['|', '/', '-', '\\']
    idx = 0
    while not stop_event.is_set():
        print(f"\r[Gemini réfléchit...] {chars[idx % len(chars)]}", end="", flush=True)
        idx += 1
        time.sleep(0.1)
    print("\r" + " " * 30 + "\r", end="", flush=True)


def extract_single_range(lines, r_string, file_path):
    """Extrait une seule plage de lignes"""
    try:
        start, end = map(int, r_string.split('-'))
        part = lines[start - 1:end]
        return f"--- {file_path} (Lignes {r_string}) ---\n" + "".join(part)
    except Exception as e:
        return f"  [!] Erreur sur la plage {r_string}: {e}"


def run():
    print("=== ASSISTANT DE CONTEXTE GEMINI ===")

    main_prompt = input("Votre question / instruction : ").strip()
    if not main_prompt:
        print("Erreur : Le prompt est obligatoire.")
        return

    context_blocks = []
    while True:
        f_input = input("\nFichier (Nom ou Chemin / TAB / Entrée pour passer à l'envoi) : ").strip()
        if not f_input:
            break

        f_path = f_input.replace('"', '').replace("'", "")

        if not os.path.exists(f_path):
            print(f"  Recherche de '{f_path}'...")
            found = find_file_recursive(f_path)
            if found:
                print(f"  Trouvé : {found}")
                f_path = found
            else:
                print(f"  Erreur : Impossible de localiser le fichier.")
                continue

        # Lecture du fichier une seule fois pour toutes ses plages
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"  Erreur de lecture : {e}")
            continue

        # --- Sous-boucle pour les plages (Ranges) ---
        file_parts = []
        while True:
            r_input = input(
                f"  Ajouter une plage pour '{os.path.basename(f_path)}' (ex: 10-50 / Entrée si fini) : ").strip()
            if not r_input:
                # Si aucune plage n'a été saisie du tout, on prend tout le fichier
                if not file_parts:
                    context_blocks.append("".join(lines))
                    print(f"  -> Fichier complet ajouté.")
                break

            part = extract_single_range(lines, r_input, f_path)
            file_parts.append(part)
            print(f"  [+] Plage {r_input} ajoutée.")

        if file_parts:
            context_blocks.append("\n\n[...]\n\n".join(file_parts))

    if not context_blocks and not main_prompt:
        return

    full_context = "\n\n---\n\n".join(context_blocks)
    ask_script = os.environ.get('ASK_SCRIPT', r'C:\Users\bulam\.local\bin\ask.py')
    python_bin = os.environ.get('PYTHON_BIN', 'python')

    stop_spinner = threading.Event()
    spinner_thread = threading.Thread(target=spinner_task, args=(stop_spinner,))

    try:
        spinner_thread.start()

        process = subprocess.Popen(
            [python_bin, ask_script, main_prompt],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8'
        )

        stdout, stderr = process.communicate(input=full_context)

        stop_spinner.set()
        spinner_thread.join()

        if process.returncode != 0:
            print(f"Erreur API : {stderr}")
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('historique_global.md', 'a', encoding='utf-8') as h:
            h.write(f"\n{'=' * 50}\nDATE : {timestamp}\nPROMPT : {main_prompt}\n{'-' * 50}\n{stdout}")
        with open('dernier_plan.md', 'w', encoding='utf-8') as p:
            p.write(stdout)

        print("\n=== RÉPONSE DE GEMINI ===\n")
        print(stdout)

    except Exception as e:
        stop_spinner.set()
        if spinner_thread.is_alive(): spinner_thread.join()
        print(f"\nErreur système : {e}")


if __name__ == "__main__":
    run()
