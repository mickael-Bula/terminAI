import os
import re
import subprocess
import io
import sys
import time
from pathlib import Path
import psycopg2
import tempfile
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
import requests
import json
from cryptography.fernet import Fernet

# --- Importations Saisie (prompt_toolkit) ---
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

# --- Importations Design (rich) ---
from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.markup import escape

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
AIDER_CONFIG_PATH = Path(LOCAL_BIN) / ".aider.conf.yml"
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


class SmartCompleter(Completer):
    def __init__(self):
        self.modes = {
            '@plan': 'Générer un plan d\'action JSON',
            '@chat': 'Discuter librement avec l\'IA',
            '@apply': 'Appliquer le plan actuel',
            '@discovery': 'Lancer une phase d\'exploration',
            '@quit': 'Quitter l\'outil',
            '@exit': 'Quitter l\'outil',
            '@show': 'Afficher le dernier plan',
            '@reset': 'Supprimer le dernier plan',
        }
        self.file_completer = PathCompleter()

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Si on commence par @, on suggère les modes
        if text.startswith('@'):
            for mode, desc in self.modes.items():
                if mode.startswith(text.lower()):
                    yield Completion(mode, start_position=-len(text), display_meta=desc)
            return

            # Sinon, on propose les fichiers (utile pour citer un fichier dans une question).
        yield from self.file_completer.get_completions(document, complete_event)


# Instance globale
command_completer = SmartCompleter()


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
        # On peut aussi ajouter --no-git pour accélérer si on n'est pas dans un repo.
        cmd = [
            "aider",
            "--model", "openrouter/google/gemini-2.0-flash-001",  # On force le modèle économe
            "--show-repo-map",
            "--map-tokens", "1024",
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

        # On force la clé API
        env["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY")

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=env,  # Utilisation de l'env configuré
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


def get_user_input(current_mode="CHAT"):
    # 1. Configuration des couleurs (Rich utilise des noms ou Hex, prompt_toolkit accepte Hex)
    # Déclare une couleur pour chaque mode.
    config = {
        "APPLY": {"hex": "#ffff00"},  # Jaune pur
        "CHAT": {"hex": "#00ffff"},  # Cyan pur
        "DISCOVERY": {"hex": "#ff00ff"},  # Magenta pur
        "PLAN": {"hex": "#00ff00"}  # Vert pur
    }

    mode_info = config.get(current_mode, config["CHAT"])
    active_hex = mode_info["hex"]

    # 2. Style pour prompt_toolkit (Le menu de complétion)
    style = Style.from_dict({
        'prompt': f'{active_hex} ',
        # On harmonise la barre de sélection du menu avec la couleur du mode
        'completion-menu.completion': 'bg:#222222 #ffffff',
        'completion-menu.completion.current': f'bg:{active_hex} #000000',
        'completion-menu.meta.completion': 'bg:#444444 #cccccc',
    })

    # 3. Affichage du Panel Rich (Harmonisé)
    console.print(Panel(
        f"[dim]Alt+Entrée pour valider | Ctrl+C pour quitter[/dim]",
        title=f"[{active_hex}]MODE {current_mode}[/{active_hex}]",
        title_align="left",
        border_style=active_hex,  # Bordure harmonisée
        expand=False
    ))

    console.print(f"[{active_hex}]\nQUESTION :[/{active_hex}]")

    # 4. Saisie avec prompt_toolkit
    text = prompt(
        HTML(f'<prompt> > </prompt>'),
        multiline=True,
        style=style,
        completer=command_completer,
        complete_while_typing=True
    )

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
    text = text.replace('\r\n', '\n')

    # Supprime les espaces inutiles en fin de bloc, mais garde la structure globale
    return text.rstrip()


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


def get_system_prompt(mode="PLAN", original_query=""):
    """Centralise les instructions de rôle et le contrat JSON."""

    # Le contrat JSON est le même pour PLAN et DISCOVERY
    json_contract = """
    RÉPONDS UNIQUEMENT EN JSON PUR.
    STRUCTURE : {"steps": 
                    [{"id": 1, "tool": "aider|shell|get_repo_map", "files": [], "instruction": "", "description": ""}]
                }

    RÈGLES STRICTES :
    1. Outils autorisés : 'get_repo_map' (exploration), 'aider' (lecture/écriture), 'shell' (terminal).
    2. INTERDICTION : 'read', 'view', 'search_string', 'grep'. Utilise 'aider' pour lire.
    3. 'files' doit TOUJOURS être une liste [], même pour un seul fichier.
    """

    if mode == "PLAN":
        # On passe par une variable intermédiaire pour ne pas avoir à doubler les accolades du JSON dans une f-string
        instruction = """
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
            
            RÈGLE D'OR POUR L'ATTRIBUT 'instruction' :
            - Rédige l'instruction comme un ordre direct, technique et chirurgical à un exécuteur.
            - Ne donne pas d'explications contextuelles inutiles 
                (le contexte est déjà dans le fichier instructions.md d'Aider).
            - Exemple : "Dans src/Entity/User.php, ajoute une propriété 'age' (int) 
                avec attributs ORM et getters/setters."
            """
        return f"{instruction}\n{json_contract}"

    if mode == "DISCOVERY":
        return f"""
            TU ES UN STRATÈGE TECHNIQUE. 
            Tu viens de recevoir la structure du projet (repo_map). 
            Analyse-la pour répondre à la question : '{original_query}'.
            Génère un NOUVEAU plan d'action détaillé pour résoudre la requête.

            {json_contract}

            RÈGLE SPÉCIFIQUE DISCOVERY :
            Maintenant que tu as la carte, privilégie 'aider' pour lire/analyser les fichiers pertinents.
            """

    return "Réponds en tant qu'expert technique. Analyse et suggère des solutions."


def execute_agentic_loop(plan, original_query, discovery_depth=0):
    # Sécurité : pas plus de 2 réévaluations automatiques par mission
    if discovery_depth > 2:
        console.print(
            f"[bold red]⚠️ Profondeur de découverte maximale atteinte. "
            f"Arrêt pour éviter une boucle infinie.[/bold red]")
        return None

    steps = plan.get("steps", [])
    total = len(steps)

    for i, step in enumerate(steps, 1):
        tool = str(step.get("tool", "")).lower()

        # --- 1. AUTOMATISATION DE L'EXPLORATION (SANS PROMPT) ---
        if tool == "get_repo_map":
            with console.status("[bold blue]🔍 Exploration automatique du projet...[/bold blue]"):
                repo_data = get_repo_map()

            if repo_data:
                # On prépare la réévaluation immédiatement
                role_discovery = get_system_prompt("DISCOVERY")
                full_prompt = f"{role_discovery}\n\n[REPO_MAP]\n{repo_data}\n\nQUESTION : {original_query}"

                # On appelle le relais pour le nouveau plan
                proc = subprocess.run(
                    [sys.executable, GLOG_PATH, original_query, "--mode", "PLAN", "--discovery"],
                    input=full_prompt.encode('utf-8'),
                    capture_output=True,
                    text=False
                )

                new_plan_raw = proc.stdout.decode('utf-8', errors='replace').strip()
                new_plan = parse_ai_plan(new_plan_raw)

                if new_plan and "steps" in new_plan:
                    console.print("[green]✨ Structure intégrée. Nouveau plan généré.[/green]")
                    # RÉCURSION : On lance le nouveau plan
                    return execute_agentic_loop(new_plan, original_query, discovery_depth + 1)

            # Si on arrive ici, c'est que le repo_map a été fait, on passe à la suite
            continue

        # --- 2. VALIDATION MANUELLE POUR LES AUTRES OUTILS ---
        # (Le code suivant ne sera exécuté QUE pour 'aider' ou 'shell')

        description = step.get("description") or "Action en cours"
        console.print(f"\n[bold cyan]Étape {i}/{total} :[/bold cyan] {description}")

        # Utilisation de prompt() HORS de console.status
        choice = prompt(HTML("<b><ansiyellow>Exécuter ? [o/s/q] ></ansiyellow></b> ")).strip().lower()

        if choice == 'q':
            break
        if choice == 's':
            continue

        # --- 3. EXÉCUTION DES OUTILS STANDARDS ---
        execute_standard_tool(step)
    return None


def execute_standard_tool(step):
    """Gère l'exécution technique des outils Aider et Shell."""
    tool = str(step.get("tool", "")).lower()
    files = step.get("files") or []
    if isinstance(files, str):
        files = [files]

    success = False

    # On calcule l'instruction
    instruction = step.get("instruction") or step.get("description") or "Action"

    if tool == "shell":
        cmd = step.get("command")
        if not cmd:
            console.print("[red]❌ Commande shell manquante.[/red]")
            return False

        with console.status(f"[bold blue]Running:[/bold blue] {cmd}"):
            # On utilise shell=True pour les commandes complexes
            result = subprocess.run(cmd, shell=True, capture_output=True, text=False)
            if result.returncode == 0:
                success = True
                console.print("[bold green]✅ Succès[/bold green]")
                if result.stdout:
                    output = result.stdout.decode('utf-8', errors='replace')
                    console.print(Panel(clean_output(output), title="Output", border_style="dim"))
            else:
                error = result.stderr.decode('utf-8', errors='replace')
                console.print(f"[bold red]❌ Échec (Code {result.returncode})[/bold red]")
                console.print(Panel(clean_output(error), title="Erreur", border_style="red"))

    elif tool == "aider":
        # Filtrer les fichiers qui existent vraiment pour éviter qu'Aider ne râle
        valid_files = [f for f in files if os.path.exists(f)]

        # 1. Préparation de l'environnement
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        # 2. Nettoyage de la commande
        aider_cmd = [
                        "winpty",  # Lance Aider dans un terminal winpty pour afficher les styles proprement
                        "aider",
                        "--message", instruction,
                        "--config", str(AIDER_CONFIG_PATH)
                    ] + valid_files

        # 3. Exécution propre
        # On sort du 'with' avant de lancer la commande Aider pour éviter les superpositions d'afichage
        with console.status("[bold magenta]Aider prépare les modifications...[/bold magenta]"):
            time.sleep(0.1)  # Petit délai pour laisser le spinner s'initialiser et se stabiliser
            pass  # Préparation rapide si besoin

        # Lancer le processus
        result = subprocess.run(aider_cmd, env=env)

        # Vérification du succès via le code de retour
        if result.returncode == 0:
            success = True
            # console.print est inutile ici, car Aider a déjà affiché son succès dans le terminal
        else:
            success = False
            console.print(f"[bold red]❌ Aider a rencontré un problème (Code {result.returncode})[/bold red]")

    return success


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
            # Si pas d'accolades, on tente les crochets (dans le cas où l'IA renvoie juste une liste).
            start_idx = text.find('[')
            end_idx = text.rfind(']')

        if start_idx != -1 and end_idx != -1:
            json_candidate = text[start_idx:end_idx + 1]

            # 4. Suppression des balises de code Markdown potentielles à l'intérieur du bloc
            json_candidate = re.sub(r'```json|```', '', json_candidate).strip()

            try:
                data = json.loads(json_candidate)

                # --- NORMALISATION ULTRA-ROBUSTE ---
                steps = []
                if isinstance(data, list):
                    steps = data
                elif isinstance(data, dict):
                    # On cherche toutes les variantes possibles de clés
                    steps = (data.get("steps") or
                             data.get("plan") or
                             data.get("PLAN") or
                             data.get("actions") or
                             [])

                    # Si le dictionnaire n'a pas ces clés, mais ressemble à une étape unique
                    if not steps and ("tool" in data or "step" in data):
                        steps = [data]

                # On reconstruit toujours un dictionnaire propre avec la clé "steps".
                return {"steps": steps}

            except json.JSONDecodeError:
                # Tentative de sauvetage : corriger les erreurs communes (virgules traînantes)
                try:
                    # Supprime une virgule juste avant un crochet ou une accolade fermante
                    json_str = re.sub(r',\s*([]}])', r'\1', json_candidate)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None

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
    if not plan or "steps" not in plan or not plan["steps"]:
        console.print("[bold yellow]⚠️ Le plan est vide ou mal formé.[/bold yellow]")
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

        # On affiche soit les fichiers (Aider), soit la commande (Shell).
        if tool == "AIDER":
            target = ", ".join(step.get("files", []))
        else:
            # On nettoie la commande shell au cas où elle contiendrait des accents
            target = clean_encoding_for_terminal(step.get("command", ""))

        table.add_row(status_icon, s_id, tool, desc, target)

    console.print(table)
    console.print(
        f"[dim italic]Tapez [/dim italic][bold cyan]@apply[/bold cyan][dim italic] pour lancer l'exécution ou "
        f"[/dim italic][bold yellow]@chat[/bold yellow][dim italic] pour modifier le plan.[/dim italic]\n")


def save_plan(plan):
    """Sauvegarde le plan actuel sur le disque de manière atomique pour éviter la corruption."""
    # Création d'un fichier temporaire dans le dossier courant
    fd, temp_path = tempfile.mkstemp(dir=".", suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            json.dump(plan, tmp, indent=4, ensure_ascii=False)

        # Remplacement atomique du fichier final par le temporaire
        # Sur Windows, la fonction 'replace' du module 'os' écrase le fichier existant sans lever une erreur.
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
        except (UnicodeEncodeError, UnicodeDecodeError):
            # En dernier recours, on vire les caractères non-ascii pour éviter les losanges
            return "".join(i for i in text if ord(i) < 128)


# --- Fonction Principale ---

def run():
    console.clear()
    current_plan = load_plan()

    # Récupère l'original_query si le plan existe, sinon chaîne vide
    original_query = current_plan.get("original_query", "") if current_plan else ""

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
        main_prompt = get_user_input(current_mode=state)  # Utilise la fonction prompt_toolkit existante

        # --- Gestion des commandes de mode ---
        if main_prompt.startswith('@'):
            cmd = main_prompt[1:].lower()
            if cmd in ['plan', 'chat', 'apply', 'discovery']:
                state = cmd.upper()
                console.clear()
                continue  # On relance la boucle pour afficher le nouveau panel

            # --- Gestion des Commandes de Bascule ---
            elif cmd in ["@exit", "exit", "@quit", "quit"]:
                break

        clean_prompt = re.sub(
            r'^@(plan|chat|apply|discovery|reset|show)\s*',
            '',
            main_prompt,
            flags=re.IGNORECASE
        ).strip()

        if not main_prompt:
            console.print("[bold red]Erreur : Question obligatoire.[/bold red]")
            continue

        # Si le mode reset est sélectionné, on supprime le plan
        if main_prompt.startswith("@reset"):
            if os.path.exists(PLAN_FILE):
                os.remove(PLAN_FILE)
                current_plan = None
                console.print("[bold green]♻️ Plan supprimé. Vous repartez sur une base propre.[/bold green]")
            continue

        if main_prompt.startswith("@chat"):
            state = "CHAT"
            console.print("[bold green]✅ Mode Architecte activé.[/bold green]")
            continue

        if main_prompt.startswith("@apply"):
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
                    # RÉCUPÉRATION DU VRAI PROMPT :
                    # On utilise le prompt qui a servi à créer le plan (stocké dans le JSON ou une variable)
                    original_query = current_plan.get("original_query", "Tâche en cours")

                    # Exécution du plan
                    execute_agentic_loop(current_plan, original_query)

                    # Une fois le plan totalement réalisé, on supprime le fichier
                    if is_plan_fully_completed(current_plan):
                        state = "CHAT"
                        console.print("\n[bold green]✨ Mission accomplie. Retour au MODE CHAT.[/bold green]")
            else:
                console.print("[bold red]⚠️ Erreur : Aucun plan n'est chargé. Générez-en un avec /plan[/bold red]")
            continue

        # --- Commande @show ---
        if main_prompt.startswith("@show"):
            if current_plan:
                display_plan_table(current_plan)
            else:
                console.print("[yellow]Aucun plan en mémoire.[/yellow]")
            continue

        if main_prompt.startswith("@plan"):
            state = "PLAN"

            # Extraction propre
            temp_prompt = main_prompt[5:].strip()

            if temp_prompt:
                original_query = temp_prompt
                console.print(f"[bold yellow]📋 Mission : {original_query}[/bold yellow]")
            elif not original_query:
                # Cas où l'utilisateur tape juste @plan sans mission préalable
                console.print(
                    "[red]❌ Erreur : Précisez votre mission après @plan (ex: @plan Créer une page de login)[/red]")
                continue

        # --- Phase de Collecte de Contexte (Commune à CHAT et PLAN) ---
        # Note : On ne demande les fichiers que si on n'est pas déjà en train de dérouler un plan
        context_blocks = []

        # 2. Affichage du panneau d'instruction pour la phase de fichiers (mode chat)
        if not main_prompt.startswith("@") or main_prompt.startswith("@chat"):
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

            # On crée un PathCompleter pour les fichiers
            file_completer = PathCompleter()

            while True:
                f_input = prompt(HTML("<ansicyan><b>Fichier :</b></ansicyan> "), completer=file_completer).strip()
                if not f_input:
                    break

                # --- AUCOMPLÉTION DES CHEMINS ---
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
                embedding = get_remote_embedding(main_prompt)

                if embedding is None:
                    context_vectoriel = "Indisponible (erreur embedding)."
                else:
                    # Étape B : Connexion DB
                    conn = psycopg2.connect(**DB_CONFIG)
                    register_vector(conn)
                    cur = conn.cursor()

                    # Étape C : Requête SQL
                    cur.execute("SELECT content "
                                "FROM chat_history "
                                "WHERE project_id = %s "
                                "ORDER BY embedding <=> %s::vector "
                                "LIMIT 3",
                                (project_id, embedding,))

                    rows = cur.fetchall()
                    # TODO : log à supprimer
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
            role_instruction = get_system_prompt("PLAN")
        elif state == "DISCOVERY":  # Le mode appelé après get_repo_map
            role_instruction = get_system_prompt("DISCOVERY", original_query)
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

            # On prépare les arguments. On ajoute --mode selon l'état actuel
            cmd = [PYTHON_BIN, GLOG_PATH, main_prompt, "--mode", state]

            # Si on est en mode PLAN, on ajoute --yes pour l'automatisation
            if state == "PLAN":
                cmd.append("--yes")

            # Crée une copie de l'environnement et force PYTHONIOENCODING
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            # --- DEBUG STRATÉGIQUE ---
            console.print(Rule("[bold purple]DEBUG : CONTENU ENVOYÉ À L'IA[/bold purple]"))
            # On affiche les 500 premiers caractères pour voir si les instructions JSON sont là
            console.print(f"[dim]{escape(full_prompt[:500])}...[/dim]")
            console.print(Rule(style="bold purple"))

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
                last_ai_response = stdout_output.strip()
                plan: dict = parse_ai_plan(last_ai_response)

                if plan:
                    if isinstance(plan, dict):
                        # On injecte le prompt propre (celui sans la commande /plan)
                        plan["original_query"] = clean_prompt

                        # On met à jour la variable de scope
                        original_query = clean_prompt

                        current_plan = plan
                        save_plan(current_plan)

                        display_plan_table(current_plan)
                        console.print(f"[bold green]✅ Plan chargé et sauvegardé. [/bold green]")
                    else:
                        console.print("[bold red]❌ Le format du plan reçu est invalide (Attendu: Dict).[/bold red]")
                else:
                    console.print("[bold red]❌ Erreur de structure JSON reçue du relais.[/bold red]")
            else:
                # Mode CHAT classique
                console.print(stdout_output)

        except Exception as e:
            console.print(f"[bold red]Erreur : {e}[/bold red]")


if __name__ == "__main__":
    run()
