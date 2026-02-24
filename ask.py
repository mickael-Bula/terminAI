import os
import sys
import re
import time
from openai import OpenAI
from openai.types.chat import ChatCompletionUserMessageParam
from dotenv import load_dotenv
from rich.console import Console

# --- Configuration de l'environnement ---
load_dotenv()

# Force le chemin vers les bibliothèques Laragon si nécessaire
site_packages = r"c:\laragon\bin\python\python-3.10\lib\site-packages"
if site_packages not in sys.path:
    sys.path.append(site_packages)

# On utilise stderr pour que les logs ne soient pas capturés dans la réponse finale
console = Console(stderr=True)


# --- Cœur du système de questionnement ---

def ask_question(user_prompt):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )

    # Votre pile de modèles (Failover)
    models = [
        # "deepseek/deepseek-r1:freedom",  # Pour tester l'échec 402/404
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-pro-exp-02-05:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/auto"
    ]

    with console.status("[bold blue]Initialisation de la requête...[/bold blue]", spinner="dots") as status:
        for model_name in models:
            # On met à jour le texte du spinner sans détruire l'objet
            status.update(f"[bold blue]Réflexion avec {model_name}.../[bold blue]")

            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[ChatCompletionUserMessageParam(role="user", content=user_prompt)],
                    temperature=0.7
                )

                raw_content = response.choices[0].message.content
                clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

                # Succès ! On stocke le nom du gagnant
                winner = model_name
                break  # On casse la boucle for

            except Exception as e:
                error_msg = str(e)
                # On utilise console.print (qui va forcer le spinner à se suspendre un instant)
                console.print(f"[bold red]⚠️  ÉCHEC : {model_name}[/bold red]")

                passable_errors = ["429", "404", "402", "NOT_FOUND", "500", "503", "CREDITS", "BALANCE"]
                if any(err in error_msg.upper() for err in passable_errors):
                    console.print(f"[bold red]   CAUSE : {error_msg[:80]}...[/bold red]")
                    console.print(f"[cyan]🔄 Passage au modèle suivant...[/cyan]")
                    time.sleep(0.3)
                    continue

                raise e
        else:
            # Si la boucle finit sans break
            return None

    console.print(f"[bold green]✅ Réponse générée par : {winner}[/bold green]")
    return clean_content


# --- Gestion des entrées et du workflow ---

def ask():
    # Lecture du prompt système (si présent)
    system_prompt_path = r"C:\Users\bulam\.local\bin\prompt_system.txt"
    system_content = ""
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            system_content = f.read().strip()

    # Capture du flux (Pipe) ou des arguments
    pipe_content = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    user_query = " ".join(sys.argv[1:]).strip()

    # Assemblage final
    parts = []
    if system_content:
        parts.append(f"### SYSTEM INSTRUCTIONS ###\n{system_content}")
    if pipe_content:
        parts.append(f"### CONTEXT ###\n{pipe_content}")
    if user_query:
        parts.append(f"### USER QUERY ###\n{user_query}")

    prompt_final = "\n\n---\n\n".join(parts)

    if not prompt_final.strip():
        console.print("Usage: glog 'votre question' ou cat file | glog")
        return

    try:
        response = ask_question(prompt_final)
        # On utilise le print() natif, glog se chargeant d'ajouter les styles.
        if response:
            print(response)
    except Exception as e:
        console.print(f"Erreur fatale : {e}")
        sys.exit(1)


if __name__ == "__main__":
    ask()
