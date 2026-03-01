import os
import hashlib
import psycopg2
from pgvector.psycopg2 import register_vector
from google import genai

# NOTE : Port 5433 si tu as choisi la Solution 1
DB_CONFIG = "host=localhost port=5433 dbname=gemini_history user=bulam password=your_secure_password"
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def get_hash(text):
    """Génère une empreinte unique pour le texte."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def index_file(filepath):
    conn = psycopg2.connect(DB_CONFIG)
    register_vector(conn)
    cur = conn.cursor()

    # On s'assure que la table a une colonne pour le hash
    cur.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS content_hash TEXT UNIQUE;")
    conn.commit()

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        # On sépare par le délimiteur exact
        blocks = content.split("==================================================")

        for block in blocks:
            text = block.strip()
            if not text or len(text) < 10:
                continue  # On ignore les blocs vides ou trop courts

            content_hash = get_hash(text)

            # Vérification de l'existence
            cur.execute("SELECT id FROM chat_history WHERE content_hash = %s", (content_hash,))
            if cur.fetchone():
                continue  # Déjà indexé, on passe au suivant

            print(f"✨ Nouvel extrait trouvé. Indexation vectorielle...")

            try:
                # 1. Génération de l'embedding (768 dim pour text-embedding-004)
                res = client.models.embed_content(model="text-embedding-004", contents=text)
                embedding = res.embeddings[0].values

                # 2. Insertion
                cur.execute(
                    "INSERT INTO chat_history (content, content_hash, embedding) VALUES (%s, %s, %s)",
                    (text, content_hash, embedding)
                )
                conn.commit()
            except MemoryError as e:
                print(f"❌ Mémoire insuffisante pour l'embedding : {e}")
                conn.rollback()
            except Exception as e:
                print(f"❌ Erreur sur ce bloc : {e}")
                conn.rollback()

    cur.close()
    conn.close()
    print("🚀 Base de données synchronisée !")


if __name__ == "__main__":
    index_file("historique_global.md")
