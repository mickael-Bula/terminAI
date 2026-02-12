import os
import re
from google import genai
from dotenv import load_dotenv

load_dotenv()


def get_last_interaction():
    """Récupère la dernière interaction depuis les fichiers locaux."""
    user_query = "Inconnue"
    ai_response = "Aucune réponse trouvée."

    # 1. Extraire la dernière question de l'historique
    if os.path.exists('historique_global.md'):
        with open('historique_global.md', 'r', encoding='utf-8') as f:
            content = f.read()
            # On cherche le dernier bloc PROMPT : ...
            matches = re.findall(r"PROMPT : (.*?)\n", content)
            if matches:
                user_query = matches[-1]

    # 2. Lire le dernier plan (la réponse de l'IA)
    if os.path.exists('dernier_plan.md'):
        with open('dernier_plan.md', 'r', encoding='utf-8') as f:
            ai_response = f.read()

    return user_query, ai_response


def run_consolidation():
    print("🔄 Initialisation de la consolidation YAML...")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Erreur : GEMINI_API_KEY non trouvée.")
        return

    client = genai.Client(api_key=api_key)
    summary_file = 'resume_contexte.yaml'

    # Chargement des données locales
    user_query, ai_response = get_last_interaction()

    if os.path.exists(summary_file):
        with open(summary_file, 'r', encoding='utf-8') as f:
            old_summary = f.read()
    else:
        old_summary = "summary: {objective: 'Initialisation', decisions: {confirmed: [], rejected: []}}"

    # On tronque la réponse IA pour économiser les tokens et éviter le 429
    short_ai_response = ai_response[:1000] + "\n[...]"

    prompt_consolidation = f"""
Tu es un expert en archivage technique. Tu dois mettre à jour la mémoire YAML.

MÉMOIRE ACTUELLE :
{old_summary}

DERNIÈRE INTERACTION :
Utilisateur : {user_query}
IA : {short_ai_response}

RÈGLES :
1. Produis UNIQUEMENT du YAML.
2. Garde les décisions confirmées précédentes.
3. Ajoute les nouvelles décisions extraites de la dernière interaction.
4. Format : summary -> objective, constraints, decisions (confirmed/rejected), open_questions.
"""

    print(f"📡 Envoi au modèle Lite pour résumé...")
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt_consolidation
        )
        # Traitement du YAML
        clean_yaml = response.text.replace('```yaml', '').replace('```', '').strip()

        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(clean_yaml)

        print(f"✅ Consolidation réussie dans {summary_file}")
        print("\n--- APERÇU DU YAML ---")
        print(clean_yaml)

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            print("\n❌ QUOTA ÉPUISÉ POUR AUJOURD'HUI.")
            # Extraction du temps d'attente suggéré par Google
            wait_match = re.search(r"retry in ([\d\.]+)s", error_msg)
            if wait_match:
                print(f"💡 Google suggère d'attendre {wait_match.group(1)} secondes.")
            print("👉 Conseil : Change de clé API ou attends demain pour la consolidation.")
        else:
            print(f"❌ Erreur API : {e}")


if __name__ == "__main__":
    run_consolidation()
