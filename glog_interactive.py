import os
import subprocess
import datetime
import glob

# Tentative d'import de pyreadline pour l'auto-complétion sous Windows
try:
    import readline


    def completer(text, state):
        """Fonction d'auto-complétion des chemins de fichiers."""
        # On utilise glob pour lister les fichiers correspondants au texte saisi
        options = glob.glob(text + '*')
        if state < len(options):
            # Ajoute un slash si c'est un dossier pour faciliter la navigation
            option = options[state]
            if os.path.isdir(option):
                return option + os.sep
            return option
        return None


    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    # Définit les délimiteurs pour que les chemins avec slashs soient bien gérés
    readline.set_completer_delims(' \t\n;')
except ImportError:
    # On définit readline à None pour éviter l'avertissement de variable non définie
    readline = None
    print("Note: Installez 'pyreadline3' pour l'auto-complétion (pip install pyreadline3)")


def get_input(prompt_text):
    return input(prompt_text).strip()


def extract_ranges(file_path, line_ranges):
    if not line_ranges:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        parts = []
        for r in line_ranges.split(','):
            start, end = map(int, r.split('-'))
            part = lines[start - 1:end]
            parts.append(f"--- {file_path} (Lignes {r}) ---\n" + "".join(part))
        return "\n\n[...]\n\n".join(parts)
    except Exception as e:
        return f"Erreur sur le fichier {file_path}: {e}"


def run():
    print("=== ASSISTANT DE CONTEXTE GEMINI ===")

    # 1. Le Prompt
    main_prompt = get_input("Votre question / instruction : ")
    if not main_prompt:
        print("Erreur : Le prompt est obligatoire.")
        return

    # 2. Les Fichiers
    context_blocks = []
    while True:
        # Ici, la touche TAB fonctionnera pour f_path
        f_path = get_input("\nFichier à ajouter (TAB pour compléter, Entrée pour terminer) : ")
        if not f_path:
            break

        # Nettoyage des éventuels guillemets ajoutés par un copier-coller de chemin
        f_path = f_path.replace('"', '').replace("'", "")

        if not os.path.exists(f_path):
            print(f"Fichier '{f_path}' introuvable.")
            continue

        ranges = get_input(f"Plages de lignes pour '{f_path}' (ex: 1-20,150-180 ou Entrée pour tout) : ")
        content = extract_ranges(f_path, ranges)
        context_blocks.append(content)

    # 3. Compilation finale
    full_context = "\n\n---\n\n".join(context_blocks)

    # 4. Exécution (Appel à ask.py)
    ask_script = os.environ.get('ASK_SCRIPT', r'C:\Users\bulam\.local\bin\ask.py')
    python_bin = os.environ.get('PYTHON_BIN', 'python')

    try:
        process = subprocess.Popen(
            [python_bin, ask_script, main_prompt],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )

        stdout, stderr = process.communicate(input=full_context)

        if process.returncode != 0:
            print(f"Erreur : {stderr}")
            return

        # 5. Journalisation
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"\n{'=' * 50}\nDATE : {timestamp}\nPROMPT : {main_prompt}\n{'-' * 50}\n{stdout}"

        with open('historique_global.md', 'a', encoding='utf-8') as h:
            h.write(log_entry)
        with open('dernier_plan.md', 'w', encoding='utf-8') as p:
            p.write(stdout)

        print("\n=== RÉPONSE DE GEMINI ===\n")
        print(stdout)

    except Exception as e:
        print(f"Erreur système : {e}")


if __name__ == "__main__":
    run()
