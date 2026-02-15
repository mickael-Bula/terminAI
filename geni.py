import os
import subprocess
import sys
import psycopg2
from pgvector.psycopg2 import register_vector
from google import genai
from dotenv import load_dotenv

# --- Importations Saisie (prompt_toolkit) ---
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

# --- Importations Design (rich) ---
from rich.console import Console
from rich.console import Group
from rich.panel import Panel

# --- Initialisation ---
console = Console()
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


def get_repo_map():
    """Génère ou récupère la carte du projet via Aider."""
    try:
        result = subprocess.run(
            ["aider", "--show-repo-map"],
            capture_output=True, text=True, encoding='utf-8'
        )
        return result.stdout
    except subprocess.SubprocessError:
        return "Impossible de générer le repo-map."


def get_user_input():
    style = Style.from_dict({
        'prompt': '#00ffff bold',
    })

    console.print(Panel(
        "[bold white]Mode interactif[/bold white]\n[dim]Alt+Entrée pour valider | Ctrl+C pour quitter[/dim]",
        title="[cyan] ASSISTANT IA (Fichiers + Mémoire + YAML) [/cyan]",
        title_align="left",
        border_style="cyan",
        expand=False
    ))

    # Saisie multi-ligne avec prompt_toolkit
    console.print("[bold cyan]\nQUESTION :[/bold cyan]")
    text = prompt(HTML('<prompt><b> > </b></prompt>'), multiline=True, style=style)
    return text.strip()


# --- Fonction Principale ---

def run():
    # 1. Nettoyage initial pour un affichage propre
    console.clear()

    main_prompt = get_user_input()

    if not main_prompt:
        console.print("[bold red]Erreur : Question obligatoire.[/bold red]")
        return

    # 2. Affichage du panneau d'instruction pour la phase de fichiers
    instruction_panel = Panel(
        Group(
            "[white]Saisissez les chemins des fichiers à inclure dans le contexte.[/white]",
            "[dim]• TAB pour auto-compléter[/dim]",
            "[dim]• ENTRÉE à vide pour valider et envoyer la requête[/dim]"
        ),
        title="[bold cyan]AJOUT DE FICHIERS[/bold cyan]",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
        expand=False
    )
    console.print(instruction_panel)

    context_blocks = []

    # Préparation du compléteur de fichiers
    file_completer = PathCompleter()

    while True:
        # Saisie du fichier avec auto-complétion intelligente
        f_input = prompt(
            HTML("<ansicyan><b>Fichier</b></ansicyan> <ansigray>(ou Entrée pour terminer) :</ansigray> "),
            completer=file_completer
        ).strip()

        if not f_input:
            break

        f_path = f_input.replace('"', '').replace("'", "")
        if not os.path.exists(f_path):
            found = find_file_recursive(f_path)
            if found:
                f_path = found
            else:
                console.print(f"[bold red]  [!] Fichier non trouvé.[/bold red]")
                continue

        if os.path.isdir(f_path):
            console.print(f"[bold red]  [!] C'est un dossier. Choisissez un fichier.[/bold red]")
            continue

        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            file_parts = []
            while True:
                r_input = prompt(
                    f"  Plage pour '{os.path.basename(f_path)}' (ex: 10-50 / Entrée pour tout) : ").strip()

                if not r_input:
                    if not file_parts:
                        context_blocks.append(f"--- FICHIER COMPLET : {f_path} ---\n" + "".join(lines))
                        console.print(f"[green]  [+] Fichier complet ajouté.[/green]")
                    break

                part = extract_single_range(lines, r_input, f_path)
                file_parts.append(part)
                console.print(f"[green]  [+] Plage {r_input} ajoutée.[/green]")

            if file_parts:
                context_blocks.append("\n\n[...]\n\n".join(file_parts))

        except Exception as e:
            console.print(f"[bold red]  [!] Erreur de lecture : {e}[/bold red]")

    # --- Récupération des contextes (RepoMap + YAML + Vectoriel) ---
    with console.status("[bold blue]Consultation de la mémoire et du projet...[/bold blue]", spinner="dots"):

        # --- Récupération du repo_map d'Aider ---
        repo_map = get_repo_map()

        # --- Récupération Mémoires ---
        summary_content = "Aucun résumé disponible."
        if os.path.exists("resume_contexte.yaml"):
            with open("resume_contexte.yaml", "r", encoding='utf-8') as f:
                summary_content = f.read()

        console.print("[bold cyan]\n🔍 Consultation de la mémoire à long terme...[/bold cyan]")
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

    try:
        subprocess.run(
            [PYTHON_BIN, GLOG_PATH, main_prompt],
            input=full_prompt,
            text=True,
            encoding='utf-8'
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompu par l'utilisateur.[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Erreur lors de l'appel de glog : {e}[/bold red]")


if __name__ == "__main__":
    run()
