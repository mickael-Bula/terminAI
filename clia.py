import os
import re
import subprocess
import io
import sys
import psycopg2
import tempfile
import unicodedata
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
import requests
import json
from cryptography.fernet import Fernet

# --- Importations Saisie (prompt_toolkit) ---
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

# --- Importations Design (rich) ---
from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.table import Table

# Force l'encodage UTF-8 pour éviter les blocages de flux sous Windows Terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# --- Initialisation ---
console = Console()
load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY").encode()
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
RELAY_URL = os.getenv("RELAY_URL")

# --- Configuration et Chemins ---
LOCAL_BIN = os.getenv("LOCAL_BIN")
GLOG_PATH = os.path.join(LOCAL_BIN, "glog_relay.py")
PYTHON_BIN = sys.executable
PLAN_FILE = "current_plan.json"
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}


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
    """Génère ou récupère la carte du projet via Aider sans appel LLM inutile."""
    try:
        # On ajoute --map-tokens pour s'assurer qu'il génère bien la sortie
        # On peut aussi ajouter --no-git pour accélérer si on n'est pas dans un repo
        cmd = [
            "aider",
            "--model", "openrouter/google/gemini-2.0-flash-001",  # On force le modèle économe
            "--show-repo-map",
            "--map-tokens", "2048",
            "--no-gitignore",
            "--yes-always",
            "--no-show-model-warnings",
            "--no-pretty",  # Indispensable pour éviter les codes de contrôle
            "--no-suggest-shell-commands",  # Évite les calculs inutiles
            "--no-check-update"  # Gagne du temps et du flux réseau
        ]

        # On prépare un environnement qui dit à Aider qu'il n'y a PAS de terminal
        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["PYTHONIOENCODING"] = "utf-8"

        # On force la clé ici API
        env["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY")

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=env,  # Utilisation de l'env propre
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            timeout=30  # Sécurité anti-blocage
        )

        output = result.stdout.decode('utf-8', errors='replace')

        # Nettoyage : Aider envoie parfois des infos de démarrage même avec --no-pretty
        # On ne garde que ce qui ressemble à une arborescence (lignes commençant par des symboles ou des dossiers)
        lines = output.splitlines()
        clean_lines = [line for line in lines
                       if not line.startswith("Using openrouter") and "model" not in line.lower()]

        return "\n".join(clean_lines).strip()

    except Exception as e:
        return f"Erreur technique RepoMap : {e}"


def get_project_id():
    """Identifie le projet par le nom du dossier courant."""
    return os.path.basename(os.getcwd())


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


def clean_output(text):
    """Nettoie les caractères ANSI et assure un encodage propre pour Windows."""
    if not text:
        return ""

    # Si on reçoit des bytes, on décode
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')

    # Supprime les codes couleur ANSI qui font parfois bugger les Panels Rich
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)

    # Normalise les retours à la ligne
    return text.replace('\r\n', '\n').strip()


# Appel le relais pour piloter l'embedding
def get_remote_embedding(text):
    cipher = Fernet(ENCRYPTION_KEY)

    # Payload pour le relais
    data_to_send = {
        "internal_token": SECRET_TOKEN,
        "text": text
    }

    encrypted_data = cipher.encrypt(json.dumps(data_to_send).encode())

    # Appel vers l'endpoint /embed sur le relais
    try:
        # Supprime /relay de l'URL pour y ajouter /embed
        response = requests.post(f"{RELAY_URL.rsplit('/', 1)[0]}/embed", data=encrypted_data)

        if response.status_code == 200:
            return response.json()['embedding']
        else:
            raise Exception(
                f"Erreur lors de la génération de l'embedding distant: {response.status_code} - {response.text}")
    except MemoryError as e:
        console.print(f"[bold red]⚠️ Mémoire insuffisante lors de la requête d'embedding distant : {e}[/bold red]")
        return None  # Ou une valeur par défaut, selon le cas
    except Exception as e:
        console.print(f"[bold red]⚠️ Erreur lors de la requête d'embedding distant : {e}[/bold red]")
        return None


def execute_agentic_loop(plan):
    """
    Exécute le plan avec validation manuelle et contrôle des sorties.
    """
    discovery_made = False
    discovery_output = ""

    if not plan or "steps" not in plan:
        console.print("[bold red]Plan invalide ou vide.[/bold red]")
        return

    steps = plan["steps"]
    total = len(steps)

    # On s'assure que chaque étape a un champ status initial
    for step in steps:
        if "status" not in step:
            step["status"] = "pending"

    console.print(Panel(
        f"🚀 [bold]Démarrage de l'exécution[/bold]\n"
        f"L'agent va traiter {total} étapes une par une.",
        border_style="yellow"
    ))

    for i, step in enumerate(steps, 1):
        # On saute les étapes déjà marquées comme 'completed'
        if step.get("status") == "completed":
            console.print(f"[dim]⏭️ Étape {i + 1} déjà effectuée. Passage à la suivante...[/dim]")
            continue
        description = step.get("description", "Pas de description")
        tool = str(step.get("tool", "")).lower()

        # Affichage d'un en-tête d'étape clair
        console.print(f"\n[bold cyan]Step {i}/{total} :[/bold cyan] [white]{description}[/white]")

        # --- PHASE DE VALIDATION ---
        if tool == 'shell':
            action_label = f"[bold green]SHELL[/bold green] -> [dim]{step.get('command')}[/dim]"
        elif tool == 'get_repo_map':
            action_label = f"[bold blue]EXPLORER[/bold blue] -> [dim]Génération de la carte du projet[/dim]"
        else:
            action_label = f"[bold magenta]AIDER[/bold magenta] -> [dim]{step.get('files')}[/dim]"
        console.print(f"Action prévue : {action_label}")
        choice = prompt(HTML(
            f"<b><ansiyellow>Continuer ?</ansiyellow></b> "
            f"[<ansigreen>o</ansigreen>: Oui | "
            f"<ansiyellow>s</ansiyellow>: Sauter | "
            f"<ansired>q</ansired>: Quitter] > "
        )).strip().lower()

        if choice == 'q':
            console.print("[bold red]🛑 Exécution interrompue par l'utilisateur.[/bold red]")
            break
        elif choice == 's':
            console.print("[yellow]⏭️ Étape sautée.[/yellow]")
            continue
        elif choice != 'o' and choice != '':
            console.print("[dim]Entrée invalide, étape considérée comme sautée.[/dim]")
            continue

        # --- EXECUTION ---
        try:
            success = False
            if tool == "shell":
                cmd = step.get("command")
                with console.status(f"[bold blue]Running:[/bold blue] {cmd}"):
                    # On utilise shell=True pour supporter les pipes et redirections
                    # On utilise text=False pour récupérer des bytes et gérer l'encodage
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=False)

                    if result.returncode == 0:
                        success = True
                        console.print("[bold green]✅ Succès[/bold green]")
                        if result.stdout:
                            # On décode manuellement avec "ignore" ou "replace" pour les caractères rebelles
                            stdout_clean = result.stdout.decode('utf-8', errors='replace')

                            # On nettoie le texte et les accents proprement avant d'afficher dans le Panel
                            safe_output = clean_output(stdout_clean)
                            console.print(Panel(safe_output, title="Output", border_style="dim"))

                    else:
                        # On décode manuellement avec "ignore" ou "replace" pour les caractères rebelles
                        stderr_clean = result.stderr.decode('utf-8', errors='replace')
                        safe_error = clean_output(stderr_clean)

                        console.print(f"[bold red]❌ Echec (Code {result.returncode})[/bold red]")
                        console.print(Panel(safe_error, title="Erreur", border_style="red"))

            elif tool == "get_repo_map":
                with console.status("[bold blue]Génération de la carte du projet...[/bold blue]"):
                    repo_data = get_repo_map()
                    if repo_data:
                        success = True
                        # On affiche un résumé pour l'utilisateur
                        console.print(Panel(repo_data[:500] + "...", title="Repo Map (Extrait)", border_style="blue"))
                        # Optionnel : On peut stocker ce résultat pour que l'IA le voit au prochain tour
                        step["output"] = repo_data
                    else:
                        console.print("[red]❌ Impossible de générer le Repo Map.[/red]")

            elif tool == "aider":
                files = step.get("files", [])
                instruction = step.get("instruction", "")

                # Conversion auto si files est une string au lieu d'une liste
                if isinstance(files, str):
                    files = [files]

                with console.status(f"[bold magenta]Aider travaille sur {files}...[/bold magenta]"):
                    # On force le mode non-interactif et on désactive le stream pour économiser l'affichage
                    aider_cmd = [
                                    "aider",
                                    "--model", "openrouter/google/gemini-2.0-flash-001",  # Modèle économe
                                    "--message", instruction,
                                    "--yes-always",
                                    "--no-auto-commits",  # On préfère garder la main sur les commits
                                    "--no-pretty",  # Pour éviter les erreurs de console invisible
                                    "--no-show-model-warnings",
                                    "--no-stream",  # Recommandé pour subprocess
                                ] + files

                    env = os.environ.copy()
                    env["TERM"] = "dumb"  # Dit à Aider de ne pas essayer de faire du design complexe
                    result = subprocess.run(aider_cmd, capture_output=True, text=False, env=env)

                    if result.returncode == 0:
                        success = True
                        console.print(f"[bold green]✅ Fichiers modifiés : {', '.join(files)}[/bold green]")
                        # On traite la sortie d'Aider même en cas de succès
                        if result.stdout:
                            stdout_clean = result.stdout.decode('utf-8', errors='replace')
                            safe_output = clean_output(stdout_clean)
                            # On peut limiter la taille de l'output d'Aider qui est souvent très long
                            # console.print(Panel(safe_output, title="Aider Output", border_style="magenta", height=15))
                            console.print(Panel(safe_output, title="Aider Output", border_style="magenta"))
                    else:
                        # Gestion propre des erreurs
                        stderr_clean = result.stderr.decode('utf-8', errors='replace')
                        safe_error = clean_output(stderr_clean)
                        console.print(f"[bold red]❌ Erreur Aider :[/bold red]")
                        console.print(Panel(safe_error, title="Erreur Aider", border_style="red"))

        except Exception as e:
            console.print(f"[bold red]💥 Erreur critique : {e}[/bold red]")
            break

        # Si la tâche est marquée comme Success, on change le statut de chaque étape réalisée :
        if success:
            step["status"] = "completed"
            save_plan(plan)
        else:
            console.print("[yellow]⚠️ Étape non marquée comme terminée car l'outil a échoué.[/yellow]")
            if prompt("Continuer le plan malgré l'échec ? (o/N) : ").lower() != 'o':
                break

    console.print(Panel("[bold green]🏁 Fin du cycle d'exécution.[/bold green]", border_style="green"))


def parse_ai_plan(text):
    """
    Extrait et valide le JSON d'un plan d'action de manière robuste.
    Gère le texte parasite, les balises Markdown et les caractères invisibles.
    """
    if not text:
        return None

    # 1. Nettoyage préliminaire : on supprime les balises personnalisées et les espaces extrêmes
    text = text.replace("[PLAN]", "").replace("[/PLAN]", "").strip()

    # 2. Nettoyage des caractères de contrôle Windows (BOM, etc.) qui font échouer json.loads
    text = text.encode('utf-8', 'ignore').decode('utf-8')

    try:
        # 3. Extraction par bloc : on cherche le PREMIER '{' et le DERNIER '}'
        # Plus sûr que re.search pour les gros blocs JSON
        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx == -1 or end_idx == -1:
            # Si pas d'accolades, on tente les crochets (dans le cas où l'IA renvoie juste une liste)
            start_idx = text.find('[')
            end_idx = text.rfind(']')

        if start_idx != -1 and end_idx != -1:
            json_candidate = text[start_idx:end_idx + 1]

            # 4. Suppression des balises de code Markdown potentielles à l'intérieur du bloc
            json_candidate = re.sub(r'```json|```', '', json_candidate).strip()

            data = json.loads(json_candidate)

            # 5. Normalisation : on veut toujours un dictionnaire avec une clé "steps"
            if isinstance(data, list):
                return {"steps": data}
            return data

        return None
    except (json.JSONDecodeError, Exception) as e:
        # En cas d'échec, on loggue l'erreur en debug
        print(f"Debug Parsing Error: {e}")
        return None


def get_validated_plan(user_query, context, retry_count=2):
    """
    Tente d'obtenir un plan valide de l'IA avec gestion d'erreurs.
    """
    current_query = user_query
    raw_response = ""

    for i in range(retry_count):
        # Appel à glog_relay (ton script IA)
        proc = subprocess.run(
            [PYTHON_BIN, GLOG_PATH, current_query],
            input=context,
            text=True, capture_output=True, encoding='utf-8'
        )

        raw_response = proc.stdout
        plan = parse_ai_plan(raw_response)

        if plan:
            return plan, raw_response

        # Si échec, on prépare le prompt de secours pour l'itération suivante
        console.print(f"[yellow]⚠️ Tentative {i + 1} : Plan invalide, demande de correction...[/yellow]")
        current_query = (f"Le JSON précédent était invalide. "
                         f"Erreur de parsing. Renvoie uniquement le JSON corrigé pour : {user_query}"
                         "Ne mets AUCUN texte avant ou après le bloc JSON, commence directement par {.")

    return None, raw_response


def display_plan_table(plan):
    """
    Affiche le plan d'action de l'IA sous forme de tableau Rich.
    """
    if not plan or "steps" not in plan:
        console.print("[bold red]Aucun plan valide à afficher.[/bold red]")
        return

    table = Table(title="📋 PLAN D'ACTION DE L'AGENT", show_header=True, header_style="bold magenta",
                  border_style="cyan")

    table.add_column("Statut", justify="center")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Outil", style="bold yellow")
    table.add_column("Description", style="white")
    table.add_column("Fichiers / Commande", style="green")

    for step in plan["steps"]:
        # Extraction des infos avec valeurs par défaut
        status_icon = "[green]✅[/green]" if step.get("status") == "completed" else "[yellow]⏳[/yellow]"
        s_id = str(step.get("id", ""))
        tool = step.get("tool", "???").upper()
        desc = clean_encoding_for_terminal(step.get("description", ""))

        # On affiche soit les fichiers (Aider), soit la commande (Shell)
        if tool == "AIDER":
            target = ", ".join(step.get("files", []))
        else:
            # On nettoie la commande shell au cas où elle contiendrait des accents
            target = clean_encoding_for_terminal(step.get("command", ""))

        table.add_row(status_icon, s_id, tool, desc, target)

    console.print(table)
    console.print(
        f"[dim italic]Tapez [/dim italic][bold cyan]/apply[/bold cyan][dim italic] pour lancer l'exécution ou "
        f"[/dim italic][bold yellow]/chat[/bold yellow][dim italic] pour modifier le plan.[/dim italic]\n")


def save_plan(plan):
    """Sauvegarde le plan actuel sur le disque de manière atomique pour éviter la corruption."""
    # Création d'un fichier temporaire dans le dossier courant
    fd, temp_path = tempfile.mkstemp(dir=".", suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            json.dump(plan, tmp, indent=4, ensure_ascii=False)

        # Remplacement atomique du fichier final par le temporaire
        # Sur Windows, os.replace écrase le fichier existant sans erreur
        os.replace(temp_path, PLAN_FILE)
        console.print(f"[dim]💾 Plan sauvegardé dans {PLAN_FILE}[/dim]")

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        console.print(f"[bold red]❌ Échec de la sauvegarde du plan : {e}[/bold red]")


def load_plan():
    """Charge le plan depuis le disque s'il existe."""
    if os.path.exists(PLAN_FILE):
        try:
            with open(PLAN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[bold red]❌ Erreur : Le fichier {PLAN_FILE} est corrompu (JSON invalide).[/bold red]")
            console.print(f"[dim]Détail : {e}[/dim]")
            return None
        except (OSError, IOError) as e:
            console.print(f"[bold red]❌ Erreur d'accès au fichier {PLAN_FILE}.[/bold red]")
            console.print(f"[dim]{e}[/dim]")
            return None
    return None


def is_plan_fully_completed(plan):
    """Vérifie si toutes les étapes du plan sont marquées comme 'completed'."""
    if not plan or "steps" not in plan:
        return False
    return all(step.get("status") == "completed" for step in plan["steps"])


def clean_encoding_for_terminal(text):
    if not text:
        return ""
    try:
        # Si c'est déjà propre, on ne touche à rien
        return text.encode('utf-8').decode('utf-8')
    except UnicodeError:
        try:
            # On tente de réparer si c'est du latin-1 mal interprété
            return text.encode('cp1252').decode('utf-8')
        except:
            # En dernier recours, on vire les caractères non-ascii pour éviter les losanges
            return "".join(i for i in text if ord(i) < 128)


# --- Fonction Principale ---

def run():
    console.clear()
    state = "CHAT"  # États : CHAT, PLAN
    current_plan = load_plan()

    # Récupération du projet courant
    project_id = get_project_id()

    # Force l'encodage UTF-8 pour les communications avec le Shell Windows
    if sys.platform == "win32":
        os.system('chcp 65001 > nul')

    # Si un plan existe et n'est pas fini, on force le mode PLAN
    if current_plan and not is_plan_fully_completed(current_plan):
        state = "PLAN"
        console.print("[yellow]💡 Reprise du plan en cours...[/yellow]")
        display_plan_table(current_plan)
    else:
        # Sinon, on reste ou on bascule en CHAT
        state = "CHAT"
        if current_plan:  # Il est fini
            console.print("[dim]✅ Dernier plan terminé archivé. (/reset pour nettoyer)[/dim]")

    while True:
        # 1. Récupération de l'input utilisateur (Mode commande ou Chat)
        color = "cyan" if state == "CHAT" else "bold yellow"
        console.print(f"\n[bold {color}]— MODE {state} —[/bold {color}]")
        main_prompt = get_user_input()  # Utilise la fonction prompt_toolkit existante

        if not main_prompt:
            console.print("[bold red]Erreur : Question obligatoire.[/bold red]")
            continue

        # --- Gestion des Commandes de Bascule ---
        if main_prompt.lower() in ["/exit", "exit", "/quit"]:
            break

        # Si le mode reset est sélectionné, on supprime le plan
        if main_prompt.startswith("/reset"):
            if os.path.exists(PLAN_FILE):
                os.remove(PLAN_FILE)
                current_plan = None
                console.print("[bold green]♻️ Plan supprimé. Vous repartez sur une base propre.[/bold green]")
            continue

        if main_prompt.startswith("/chat"):
            state = "CHAT"
            console.print("[bold green]✅ Mode Architecte activé.[/bold green]")
            continue

        if main_prompt.startswith("/apply"):
            if state == "PLAN" and current_plan:
                # --- SÉCURITÉ ---
                if is_plan_fully_completed(current_plan):
                    console.print(Panel(
                        "[bold yellow]⚠️ Ce plan est déjà 100% terminé.[/bold yellow]\n"
                        "[dim]Pour le relancer, utilisez [/dim][bold cyan]/reset[/bold cyan][dim] ou générez un "
                        "nouveau plan.[/dim]",
                        border_style="yellow"
                    ))
                else:
                    # Exécution du plan
                    execute_agentic_loop(current_plan)

                    # Une fois le plan totalement réalisé, on supprime le fichier
                    if is_plan_fully_completed(current_plan):
                        state = "CHAT"
                        console.print("\n[bold green]✨ Mission accomplie. Retour au MODE CHAT.[/bold green]")
            else:
                console.print("[bold red]⚠️ Erreur : Aucun plan n'est chargé. Générez-en un avec /plan[/bold red]")
            continue

        # --- Ajout de la commande /show ---
        if main_prompt.startswith("/show"):
            if current_plan:
                display_plan_table(current_plan)
            else:
                console.print("[yellow]Aucun plan en mémoire.[/yellow]")
            continue

        if main_prompt.startswith("/plan"):
            state = "PLAN"
            console.print("[bold yellow]📋 Mode Planificateur activé.[/bold yellow]")
            # Si l'utilisateur a juste tapé "/plan", on s'arrête là pour ce tour
            if main_prompt.strip() == "/plan":
                continue

        # --- Phase de Collecte de Contexte (Commune à CHAT et PLAN) ---
        # Note : On ne demande les fichiers que si on n'est pas déjà en train de dérouler un plan
        context_blocks = []

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

        file_completer = PathCompleter()
        while True:
            f_input = prompt(HTML("<ansicyan><b>Fichier :</b></ansicyan> "), completer=file_completer).strip()
            if not f_input:
                break

            f_path = f_input.replace('"', '').replace("'", "")
            if not os.path.exists(f_path):
                found = find_file_recursive(f_path)
                if found:
                    f_path = found
                else:
                    console.print("[red]Fichier non trouvé.[/red]")
                    continue

            try:
                with open(f_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                r_input = prompt(f"  Plage (ex: 1-20 / Entrée pour tout) : ").strip()
                if not r_input:
                    context_blocks.append(f"--- FICHIER : {f_path} ---\n" + "".join(lines))
                else:
                    context_blocks.append(extract_single_range(lines, r_input, f_path))
            except Exception as e:
                console.print(f"[red]Erreur : {e}[/red]")

        with console.status("[bold blue]Appel du relais...[/bold blue]"):
            try:
                # Étape A : Embedding distant
                console.log(f"[dim]Debug: Demande d'embedding pour: {main_prompt[:30]}...[/dim]")
                embedding = get_remote_embedding(main_prompt)

                if embedding is None:
                    console.log("[yellow]⚠️ Warning: Embedding non récupéré, recherche vectorielle sautée.[/yellow]")
                    context_vectoriel = "Indisponible (erreur embedding)."
                else:
                    # Étape B : Connexion DB
                    console.log(f"[dim]Debug: Connexion DB ({DB_CONFIG['host']})...[/dim]")
                    conn = psycopg2.connect(**DB_CONFIG)
                    register_vector(conn)
                    cur = conn.cursor()

                    # Étape C : Requête SQL
                    console.log("[dim]Debug: Exécution recherche vectorielle...[/dim]")
                    cur.execute("SELECT content "
                                "FROM chat_history "
                                "WHERE project_id = %s "
                                "ORDER BY embedding <=> %s::vector "
                                "LIMIT 3",
                                (project_id, embedding,))

                    rows = cur.fetchall()
                    console.log(f"[dim]Debug: {len(rows)} souvenirs trouvés.[/dim]")
                    context_vectoriel = "\n".join([f"- {r[0]}" for r in rows])

                    cur.close()
                    conn.close()

            except psycopg2.OperationalError as e:
                console.print(f"[bold red]❌ Erreur de connexion DB (Docker/WSL) : {e}[/bold red]")
                context_vectoriel = "Indisponible (DB injoignable)."
            except Exception as e:
                # C'est ici qu'on attrape ce qui fait "sauter" le script
                console.print(f"[bold red]💥 Erreur imprévue dans le bloc contexte : {e}[/bold red]")
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
                context_vectoriel = "Indisponible (erreur critique)."

        # --- Ajustement du Prompt selon le Mode ---
        files_context_string = "\n\n".join(context_blocks)
        if state == "PLAN":
            role_instruction = """
            TU ES UN GÉNÉRATEUR DE JSON PUR.
            Ta mission est de planifier des actions techniques en utilisant EXCLUSIVEMENT les outils suivants :
            1. 'get_repo_map' : [PRIORITAIRE POUR L'EXPLORATION] Utilise cet outil AVANT TOUTE CHOSE 
                si tu ne connais pas l'emplacement d'un composant ou d'une fonction. 
                Il est beaucoup plus rapide et précis que 'grep'.
            2. 'aider' : Pour modifier, créer ou lire des fichiers. (Nécessite 'files' et 'instruction')
            3. 'shell' : Pour exécuter des commandes terminal (ls, mkdir, npm test, etc.). (Nécessite 'command')
                NE PAS l'utiliser pour chercher des fichiers si 'get_repo_map' suffit.

            STRUCTURE JSON OBLIGATOIRE :
            {
              "steps": [
                {
                  "id": 1,
                  "tool": "get_repo_map",
                  "description": "Exploration de la structure du projet"
                },
                {
                  "id": 2,
                  "tool": "aider",
                  "description": "Analyse du code source",
                  "files": ["src/main.js"],
                  "instruction": "Cherche la logique de connexion"
                },
                {
                  "id": 3,
                  "tool": "shell",
                  "description": "Test de connectivité réseau",
                  "command": "ping -c 4 google.com"
                }
              ]
            }

            RÈGLES CRITIQUES :
            - Ne propose JAMAIS d'outil autre que 'aider' ou 'shell'.
            - Ne mets AUCUN texte avant ou après le JSON.
            - Pas de balises [PLAN], pas de commentaires.
            - Retourne uniquement l'objet JSON valide.

            RÈGLE DE GRANULARITÉ : 
            - Chaque étape aider ne doit cibler qu'UN SEUL fichier à la fois. 
            - Si plusieurs fichiers doivent être modifiés, crée autant d'étapes que de fichiers.
            """
        else:
            role_instruction = "\nRéponds en tant qu'expert technique. Analyse et suggère des solutions."

        full_prompt = f"""
[INSTRUCTION_ROLE]
{role_instruction}
[/INSTRUCTION_ROLE]

[STRUCTURE_DU_PROJET]
Utilise l'outil 'get_repo_map' si tu as besoin de voir l'arborescence des fichiers.
[/STRUCTURE_DU_PROJET]

[CONTEXTE_FICHIERS]
{files_context_string}
[/CONTEXTE_FICHIERS]

[CONTEXTE_VECTORIEL]
{context_vectoriel}
[/CONTEXTE_VECTORIEL]

QUESTION_UTILISATEUR : {main_prompt}"""

        # --- Appel de l'IA (glog_relay) ---
        try:
            # DEBUG : Vérifier si le fichier existe pour Windows
            if not os.path.exists(GLOG_PATH):
                console.print(f"[bold red]❌ Script IA introuvable : {GLOG_PATH}[/bold red]")
                # Si on est sous Windows, on peut essayer de convertir le chemin si besoin

            console.log(f"[dim]Debug: Exécution de {PYTHON_BIN} {GLOG_PATH}...[/dim]")

            # On prépare les arguments. On ajoute --mode selon l'état actuel
            cmd = [PYTHON_BIN, GLOG_PATH, main_prompt, "--mode", state]

            # Si on est en mode PLAN, on ajoute --yes pour l'automatisation
            if state == "PLAN":
                cmd.append("--yes")

            # Crée une copie de l'environnement et force PYTHONIOENCODING
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            proc = subprocess.run(
                cmd,
                input=full_prompt.encode('utf-8'),  # On encode l'input en bytes
                text=False,  # On désactive le décodage auto
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                env=env  # On passe l'environnement forcé
            )

            # Décodage manuel sécurisé du stderr (les logs de debug)
            if proc.stderr:
                stderr_output = proc.stderr.decode('utf-8', errors='replace')
                console.print(f"[dim]{stderr_output}[/dim]")

            # Décodage avec une sécurité supplémentaire
            stdout_output = ""
            if proc.stdout:
                # On décode les bytes reçus. Si UTF-8 échoue, on tente CP1252 et on convertit
                raw_bytes = proc.stdout
                try:
                    stdout_output = raw_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # Si Windows a forcé du CP1252, on répare
                    stdout_output = raw_bytes.decode('cp1252', errors='replace')

            if state == "PLAN":
                # On utilise la version décodée manuellement
                last_ai_response = stdout_output.strip()
                plan = parse_ai_plan(last_ai_response)

                if plan:
                    current_plan = plan
                    save_plan(current_plan)
                    display_plan_table(current_plan)
                    project_id = os.path.basename(os.getcwd())
                    console.print(f"[bold green]✅ Plan chargé et sauvegardé. [{project_id}][/bold green]")
                    console.print("[bold green]✅ Plan chargé. Tapez /apply pour exécuter.[/bold green]")
                else:
                    console.print("[bold red]❌ Erreur de structure JSON reçue du relais.[/bold red]")
                    console.print(last_ai_response)  # Affichage pour debug
            else:
                # Mode CHAT classique
                console.print(stdout_output)

        except Exception as e:
            console.print(f"[bold red]Erreur : {e}[/bold red]")


if __name__ == "__main__":
    run()
