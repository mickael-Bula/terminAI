import os
import psycopg2
import subprocess
from pgvector.psycopg2 import register_vector
from google import genai

# On définit le chemin absolu de glog.py pour qu'il soit accessible de partout
GLOG_PATH = os.path.expanduser("~/.local/bin/glog.py")

# Utilise le port 5433
DB_CONFIG = "host=localhost port=5433 dbname=gemini_history user=bulam password=your_secure_password"
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def get_semantic_context(query_text, limit=3):
    """Recherche les blocs les plus proches sémantiquement dans Postgres."""
    try:
        # 1. Générer le vecteur de la question
        res = client.models.embed_content(model="text-embedding-004", contents=query_text)
        query_embedding = res.embeddings[0].values

        # 2. Rechercher dans Postgres
        conn = psycopg2.connect(DB_CONFIG)
        register_vector(conn)
        cur = conn.cursor()

        # L'opérateur <=> calcule la distance cosinus (plus c'est petit, plus c'est proche)
        cur.execute("""
            SELECT content FROM chat_history 
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (query_embedding, limit))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        if rows:
            context = "\n### MÉMOIRE DE L'HISTORIQUE (PERTINENT) :\n"
            for i, row in enumerate(rows):
                context += f"\n--- Extrait {i + 1} ---\n{row[0]}\n"
            return context
        return ""
    except Exception as e:
        print(f"⚠️ Erreur de recherche sémantique : {e}")
        return ""


def run():
    print("=== ASSISTANT GEMINI AVEC MÉMOIRE VECTORIELLE ===")
    user_query = input("\nSaisissez votre question : ")

    # 1. On va chercher dans la base ce qui ressemble à la question
    print("🔍 Consultation de la mémoire à long terme...")
    context = get_semantic_context(user_query)

    # 2. Construction du prompt enrichi
    full_prompt = f"{context}\n\nVoici ma nouvelle question :\n{user_query}"

    # 3. Envoi à Gemini (Appel de ton script glog.py ou direct)
    print("🚀 Envoi à Gemini...")

    # On passe le prompt complet à glog.py
    subprocess.run(["python", GLOG_PATH, full_prompt])


if __name__ == "__main__":
    run()
