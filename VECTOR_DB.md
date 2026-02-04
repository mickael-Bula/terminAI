## Ajout d'une BDD vectorielle

Afin d'améliorer le contexte fourni à l'IA,
j'ajoute une base vecetorielle afin d'y enregistrer l'historique de conversation.

Dans un souci de simplicité, je commence par un container Docker.

## Container postgresql

Je configure le container dans un docker-compose :

```yaml
services:
  db-vector:
    image: pgvector/pgvector:pg16
    container_name: gemini-vector-db
    restart: always
    environment:
      POSTGRES_USER: bulam
      POSTGRES_PASSWORD: your_secure_password
      POSTGRES_DB: gemini_history
    ports:
      - "5432:5432"
    volumes:
      - pgvector_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U bulam -d gemini_history"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgvector_data:
```

## Lancement du container

```bash
$docker compose up -d
```

## Rendre la base vectorielle

Une extension est nécessaire pour permettre à la base postgresql de devenir vectorielle.
Cette extension n'est à installer qu'une seule fois, après l'initialisation de la base.
Voici la commande pour l'installer à l'intérieur du container :

```bash
$ docker exec -it gemini-vector-db psql -U bulam -d gemini_history -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## Création de la structure de la base

Il faut entrer dans le container :

```bash
$ docker exec -it gemini-vector-db psql -U bulam -d gemini_history
```

Une fois dans le container, exécuter la requête suivante :

```sql
CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    content TEXT,                -- Le texte du message (le bloc de l'historique)
    metadata JSONB,              -- Pour stocker la date, le prompt original, etc.
    embedding vector(768)       -- Vecteur (Note: 768 pour Gemini embedding-004)
);

-- Index pour accélérer la recherche de proximité
CREATE INDEX ON chat_history USING hnsw (embedding vector_cosine_ops);
```

## Les commandes PGSQL utiles

| Commande | Action                                                          |
|----------|-----------------------------------------------------------------|
| \dt      | 	Lister les tables (vérifier si chat_history est là)            |
| \dx      | Lister les extensions installées (vérifier si vector est actif) |
| \d       | chat_history	Voir la structure (colonnes) de ta table.          |
| \q       | Quitter le terminal PostgreSQL.                                 |

## Les librairies Python-PostgreSQL

```bash
pip install psycopg2-binary pgvector
```

Pour installer sur une version de Python particulière :

```bash
$ c:\laragon\bin\python\python-3.10\python.exe -m pip install psycopg2-binary pgvector
````

## Script de vectorisation

Le script se nomme `index_history.py`.
Il est placé par commodité dans le même répertoire que les autres binaires.

## Vectoriser l'historique

Pour effectuer un enregistrement sémantique dans la base postgres, 
il suffit de se placer à la racine d'un projet contenant un fichier `historique_global.md` et de lancer :

```bash
$ c:\laragon\bin\python\python-3.10\python.exe index_history.py
```

## Mise à jour du script d'interrogation de l'IA

On ajoute un appel à la base vectorielle pour améliorer le contexte de la question posée à l'IA.
Une fois la réponse fournie, on enregistre le tout dans la base pour accès future.

Toutes les modifications se trouvent dans le script `geni.py`.

## Alias pour appeler geni.py

```cmd
;= rem alias qui interroge l'IA en lui fournissant un contexte ciblé
geni=%PYTHON_BIN% %LOCAL_BIN%\geni.py
```