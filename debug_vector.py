import os
import psycopg2
import hashlib
from pgvector.psycopg2 import register_vector
from google import genai
from dotenv import load_dotenv

load_dotenv()

# --- Configuration Homelab ---
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}


def run_debug():
    print("=== DEBUG VECTOR DIMENSIONS (768) ===")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Erreur : GEMINI_API_KEY non trouvée.")
        return

    client = genai.Client(api_key=api_key)

    # Texte de test
    test_text = input("\nEntrez un texte à indexer pour le test : ").strip()
    if not test_text:
        test_text = "Test d'intégration vectorielle pour Symfony"

    print(f"\n1. 🛰️ Génération de l'embedding (Modèle 004)...")
    try:
        # Tentative avec forçage explicite de la dimension
        res = client.models.embed_content(
            model="models/gemini-embedding-001",
            contents=test_text,
            config={'output_dimensionality': 768}
        )
        embedding = res.embeddings[0].values
        dim_found = len(embedding)
        print(f"   ✅ Dimension reçue de l'API : {dim_found}")

        if dim_found != 768:
            print(f"   ⚠️ ALERTE : Reçu {dim_found} au lieu de 768 !")
    except Exception as e:
        print(f"   ❌ Erreur API : {e}")
        return

    print(f"\n2. 🐘 Connexion à PostgreSQL ({DB_CONFIG['host']})...")
    try:
        content_hash = hashlib.md5(test_text.encode('utf-8')).hexdigest()

        conn = psycopg2.connect(**DB_CONFIG)
        register_vector(conn)
        cur = conn.cursor()

        print(f"   📥 Tentative d'insertion dans {DB_CONFIG['dbname']}...")
        cur.execute(
            "INSERT INTO chat_history (content, content_hash, embedding) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (test_text, content_hash, embedding)
        )

        conn.commit()
        print("   ✅ SUCCÈS : Donnée insérée sans erreur de dimension.")

        cur.close()
        conn.close()

    except psycopg2.Error as e:
        print(f"   ❌ ERREUR POSTGRES : {e}")
        print("\n💡 Si l'erreur est 'expected 768 but got 3072', cela confirme que")
        print("   le SDK ignore 'output_dimensionality'.")
    except Exception as e:
        print(f"   ❌ Autre erreur : {e}")


if __name__ == "__main__":
    run_debug()
