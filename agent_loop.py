import subprocess

# --- Importations Saisie (prompt_toolkit) ---
from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML

# --- Importations Design (rich) ---
from rich.console import Console
from rich.panel import Panel

# --- Initialisation ---
console = Console()


def execute_agentic_loop(plan):
    """
    Parcourt les étapes du plan JSON et exécute les outils appropriés.
    """
    if not plan or "steps" not in plan:
        console.print("[bold red]Plan invalide ou vide.[/bold red]")
        return

    steps = plan["steps"]
    console.print(Panel(f"Démarrage de l'exécution de [bold]{len(steps)}[/bold] étapes", border_style="yellow"))

    for step in steps:
        step_id = step.get("id", "?")
        desc = step.get("description", "Pas de description")
        tool = step.get("tool", "").lower()

        console.print(f"\n[bold yellow]>>> Étape {step_id}: {desc}[/bold yellow]")

        # Demande de validation avant chaque étape
        confirm = prompt(HTML(
            f"<ansigray>Exécuter cette étape avec </ansigray>"
            f"<ansicyan>{tool}</ansicyan>"
            f"<ansigray> ? (O/n) : </ansigray>")).strip().lower()

        if confirm == 'n':
            console.print("[yellow]Étape sautée par l'utilisateur.[/yellow]")
            continue

        try:
            if tool == "shell":
                cmd = step.get("command")
                if cmd:
                    with console.status(f"[bold blue]Exécution shell : {cmd}...[/bold blue]"):
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                        if result.returncode == 0:
                            console.print("[green]✅ Succès (Shell)[/green]")
                            if result.stdout:
                                console.print(f"[dim]{result.stdout}[/dim]")
                        else:
                            console.print(f"[bold red]❌ Erreur Shell : {result.stderr}[/bold red]")

            elif tool == "aider":
                files = step.get("files", [])
                instruction = step.get("instruction", "")

                if not files or not instruction:
                    console.print("[red]Erreur : 'files' ou 'instruction' manquant pour Aider.[/red]")
                    continue

                with console.status("[bold magenta]Aider en cours de modification...[/bold magenta]"):
                    # On appelle Aider en mode non-interactif pour cette étape précise
                    # --yes-always évite les blocages, --message donne l'ordre
                    aider_cmd = [
                                    "aider",
                                    "--model", "openrouter/google/gemini-2.0-flash-001",
                                    "--message", instruction,
                                    "--yes-always",
                                    "--no-show-model-warnings"
                                ] + files

                    result = subprocess.run(aider_cmd, capture_output=True, text=True)

                    if result.returncode == 0:
                        console.print(f"[green]✅ Modification terminée sur {files}[/green]")
                    else:
                        console.print(f"[bold red]❌ Aider a rencontré un problème :[/bold red]\n{result.stderr}")

        except Exception as e:
            console.print(f"[bold red]💥 Erreur critique lors de l'exécution : {e}[/bold red]")
            break

    console.print(Panel("[bold green]Fin du cycle d'exécution.[/bold green]", border_style="green"))
