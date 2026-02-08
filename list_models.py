import os
from google import genai


def list_my_models():
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    print("🔎 Exploration des modèles disponibles...")
    print("-" * 50)

    try:
        models = list(client.models.list())
        if not models:
            print("Aucun modèle trouvé.")
            return

        for model in models:
            # On affiche le nom technique (c'est ce dont on a besoin)
            # Le nom est généralement dans model.name ou model.model_id
            name = getattr(model, 'name', 'Inconnu')
            print(f"📦 Modèle trouvé : {name}")

            # La première fois, on regarde ce qu'il y a dans l'objet pour comprendre l'erreur
            if model == models[0]:
                print(f"\nDebug - Attributs disponibles dans l'objet Model :")
                print([attr for attr in dir(model) if not attr.startswith('_')])
                print("-" * 50)

    except Exception as e:
        print(f"❌ Erreur : {e}")


if __name__ == "__main__":
    list_my_models()
