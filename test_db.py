import psycopg2
from pgvector.psycopg2 import register_vector
import os
from dotenv import load_dotenv

load_dotenv()


def test_connection():
    db_config = {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD")
    }

    print(f"🚀 Tentative de connexion vers {db_config['host']}...")

    try:
        # 1. Test de connexion de base
        conn = psycopg2.connect(**db_config)
        print("✅ Connexion réseau établie.")

        # 2. Test de pgvector
        register_vector(conn)
        print("✅ Extension pgvector reconnue par le client Python.")

        # 3. Test de la table
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM chat_history;")
        count = cur.fetchone()[0]
        print(f"✅ Table 'chat_history' accessible (Contient {count} entrées).")

        cur.close()
        conn.close()
        print("\n✨ TOUT EST PRÊT : Ton Homelab est opérationnel !")

    except Exception as e:
        print(f"\n❌ ÉCHEC DU TEST")
        print(f"Détail de l'erreur : {e}")
        print("\n💡 Rappels :")
        print("- Le mot de passe est-il correct ?")
        print("- Le fichier pg_hba.conf autorise-t-il l'IP de ton PC ?")
        print("- As-tu redémarré postgresql après les modifs de conf ?")


if __name__ == "__main__":
    test_connection()
