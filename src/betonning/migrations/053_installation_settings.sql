-- Installatieconfiguratie: publieke velden en versleutelde providerkeys gescheiden.
CREATE TABLE installation_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    revision INTEGER NOT NULL,
    settings_json TEXT NOT NULL,
    llm_key BLOB,
    embedding_key BLOB,
    updated_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
