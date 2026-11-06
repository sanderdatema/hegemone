-- Fase 2 (BETON-8) — typo-tolerante fuzzy zoek als fallback.
-- Naast items_fts (prefix/exact, hoge precisie, korte queries) een trigram-FTS-
-- tabel voor substring- en typo-matching. De zoeklogica gebruikt deze ALLEEN als
-- de exacte zoek niets oplevert, zodat de precisie van de exacte zoek behouden
-- blijft. Trigram-tokenizer vereist SQLite ≥ 3.34 (LXC draait 3.45).
-- Migratierunner zet PRAGMA user_version = 5 na succes.

CREATE VIRTUAL TABLE items_trgm USING fts5(
    title,
    description_md,
    content='items',
    content_rowid='id',
    tokenize='trigram'
);

-- Externe-content-FTS wordt niet automatisch gevuld: bestaande items indexeren.
INSERT INTO items_trgm(rowid, title, description_md)
    SELECT id, title, description_md FROM items;

CREATE TRIGGER items_trgm_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_trgm(rowid, title, description_md)
    VALUES (new.id, new.title, new.description_md);
END;

CREATE TRIGGER items_trgm_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_trgm(items_trgm, rowid, title, description_md)
    VALUES ('delete', old.id, old.title, old.description_md);
END;

CREATE TRIGGER items_trgm_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_trgm(items_trgm, rowid, title, description_md)
    VALUES ('delete', old.id, old.title, old.description_md);
    INSERT INTO items_trgm(rowid, title, description_md)
    VALUES (new.id, new.title, new.description_md);
END;
