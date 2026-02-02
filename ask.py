import os
import sys

# Force le chemin vers les bibliothèques Laragon
site_packages = r"c:\laragon\bin\python\python-3.10\lib\site-packages"
if site_packages not in sys.path:
    sys.path.append(site_packages)

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def ask():
    # --- Lecture du Prompt Système ---
    system_prompt_path = r"C:\Users\bulam\.local\bin\prompt_system.txt"
    system_content = ""
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            system_content = f.read().strip()

    pipe_content = ""
    file_content = ""

    # 1. Lecture du flux entrant (Pipe ou Redirection < )
    if not sys.stdin.isatty():
        pipe_content = sys.stdin.read().strip()

    # 2. Analyse des arguments
    args = sys.argv[1:]

    if "-f" in args:
        # Cas : gemini -f prompt.txt
        try:
            idx = args.index("-f")
            file_path = args[idx + 1]
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read().strip()
            # On retire -f et le nom du fichier des arguments pour le texte restant
            args.pop(idx + 1)
            args.pop(idx)
        except (IndexError, FileNotFoundError):
            print("Erreur : Fichier spécifié après -f introuvable.")
            return

    # Le reste des arguments est considéré comme la question texte
    user_query = " ".join(args).strip()

    # 3. Assemblage intelligent du Prompt
    # On combine tout ce qu'on a trouvé (Pipe + Fichier + Texte)
    parts: list[str] = []
    if system_content:
        parts.append(f"INSTRUCTIONS SYSTÈME :\n{system_content}")
    if pipe_content:
        parts.append(pipe_content)
    if file_content:
        parts.append(file_content)
    if user_query:
        parts.append(user_query)

    prompt = "\n\n---\n\n".join(parts)

    if not pipe_content and not file_content and not user_query:
        print("\n=== WORKFLOW GEMINI + AIDER ===")
        print("Usage simple :")
        print("\nUtilisation de l'alias gemini")
        print("  gemini 'Ma question'")
        print("  gemini -f instructions.txt")
        print("  cat code.php | gemini 'Analyse ce code'")
        print("  gemini < audit.txt")
        print("\n===================")
        print("\nUsage de l'alias glog, qui ajoute une journalisation des discussions :\n")
        print("  glog \"Ma question\"")
        print("\nUsage avec fichier(s) en contexte :\n")
        print("  cat fichier.php | glog \"Analyse ce code\"")
        print("  cat f1.php f2.php | glog \"Explique la relation\"")
        print("\nUsage avec instructions décrite dans un fichier texte :")
        print("  glog -f plan_migration.txt")
        print("\nUsage avec fichier en contexte et fichier d'instruction :")
        print("  cat code.php | glog -f regles.txt")
        print("\nAprès génération du plan :")
        print("  ago fichier.php")
        return

    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt
        )
        print(response.text)
    except Exception as e:
        print(f"Erreur API : {e}")


if __name__ == "__main__":
    ask()
