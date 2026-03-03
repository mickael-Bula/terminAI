CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    content TEXT,
    content_hash VARCHAR(32) UNIQUE,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ajout de la colonne project_id
ALTER TABLE chat_history
ADD COLUMN IF NOT EXISTS project_id VARCHAR(50);

-- Indexation pour des recherches rapides par projet
CREATE INDEX IF NOT EXISTS idx_chat_history_project_id ON chat_history(project_id);
