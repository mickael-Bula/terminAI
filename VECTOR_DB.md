## Ajout d'une BDD vectorielle

Afin d'améliorer le contexte fourni à l'IA,
j'ajoute une base vectorielle pour y enregistrer l'historique de conversation.

Dans un souci de simplicité, je commence par un container Docker.

Pour ne pas avoir à activer l'extension **pgvector** à chaque lancement du container,
on ajoute un fichier `01-setup.sql` pour l'activer automatiquement et, dans la foulée, créer la base et la table requise.
Ce fichier est à placer dans un dossier `init-db/` :

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    content TEXT,
    content_hash VARCHAR(32) UNIQUE,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Container postgresql

>NOTE : Sous WSL, on pourra créer un projet sous `~/terminai-db`, puis y créer le fichier `docker-compose.yml` suivant :

Je configure le container dans un docker-compose :

```yaml
services:
  db-vector:
    image: pgvector/pgvector:pg16
    container_name: pg_vector_ai
    restart: always
    environment:
    # Utilise les valeurs du .env si elles existent, sinon les valeurs par défaut
      POSTGRES_USER: ${DB_USER:-bulam}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-your_secure_password}
      POSTGRES_DB: ${DB_NAME:-gemini_history}
    ports:
      - "5432:5432"
    volumes:
      - pgvector_data:/var/lib/postgresql/data
      - ./init-db:/docker-entrypoint-initdb.d # Script d'initialisation auto
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
$ docker compose up -d
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
    embedding vector(768)       -- Vecteur (Note: 768 pour Gemini embedding-001)
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

## Création d'une base de données vectorielle sur le serveur LXC :

$ pct enter 102
> sudo -u postgres psql -c "SELECT version();"	# PostgreSQL 16.11 (Debian 16.11-1.pgdg13+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit

### installer pgvector
> apt update
> apt install postgresql-16-pgvector

#### Se connecter en tant qu'utilisateur postgres

```bash
sudo -u postgres psql
```

#### ACTIVER L'EXTENSION

```sql
pgsql# CREATE EXTENSION vector;
```

#### Vérifier le résultat

```sql
pgsql# SELECT * FROM pg_extension WHERE extname = 'vector';
```

#### (Optionnel) Créer la base si ce n'est pas fait

```sql
pgsql# CREATE DATABASE gemini_history;
```

#### Se connecter à la base

```sql
pgsql# \c gemini_history
```

#### Créer la table

```sql
pgsql# CREATE TABLE chat_history (id SERIAL PRIMARY KEY, content TEXT, content_hash VARCHAR(64) UNIQUE, embedding vector(768), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);

pgsql# CREATE INDEX ON chat_history USING hnsw (embedding vector_cosine_ops);
```

#### Créer le User et donner les droits

```sql
-- Dans le LXC : sudo -u postgres psql
pgsql# CREATE USER bulam WITH PASSWORD 'ton_password';
pgsql# GRANT ALL PRIVILEGES ON DATABASE gemini_history TO bulam;
pgsql# GRANT ALL ON SCHEMA public TO bulam; -- Nécessaire pour créer/lire les tables
```

### Alternative : modifier les droits

```sql
-- Donne la propriété de la table à bulam
ALTER TABLE chat_history OWNER TO bulam;

-- Donne les droits sur les séquences (pour l'ID auto-incrémenté)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bulam;

-- (Optionnel, mais recommandé) Donne les droits par défaut pour le futur
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO bulam;
```

### Connexion psql avec user dédié

Pour se connecter à la base vectorielle avec l'utilisateur dédié :

1. Entrer dans le cotainer postgres depuis Proxmox : `$ pct enter 102`
2. Se connecter à psql avec la chaîne suivante : `psql -h localhost -U mon_user -d ma_base`
