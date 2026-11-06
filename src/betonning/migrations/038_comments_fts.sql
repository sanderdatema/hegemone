-- BETON-370: zoeken ook in comments. FTS5 over comments (body_md + het inline
-- antwoord op een vraag-comment, BETON-265) zodat /search een ticket ook vindt
-- op een woord dat alleen in een reactie staat.
--
-- Spiegelt items_fts (001_initial.sql): external-content-tabel op comments.id
-- plus de drie triggers, inclusief de 'delete'-rij vóór de nieuwe waarde bij
-- een update. Bestaande tabellen worden niet aangeraakt (geen table-recreate).
CREATE VIRTUAL TABLE comments_fts USING fts5(
    body_md,
    answer_text,
    content='comments',
    content_rowid='id'
);

CREATE TRIGGER comments_fts_ai AFTER INSERT ON comments BEGIN
    INSERT INTO comments_fts(rowid, body_md, answer_text)
    VALUES (new.id, new.body_md, new.answer_text);
END;

CREATE TRIGGER comments_fts_ad AFTER DELETE ON comments BEGIN
    INSERT INTO comments_fts(comments_fts, rowid, body_md, answer_text)
    VALUES ('delete', old.id, old.body_md, old.answer_text);
END;

CREATE TRIGGER comments_fts_au AFTER UPDATE ON comments BEGIN
    INSERT INTO comments_fts(comments_fts, rowid, body_md, answer_text)
    VALUES ('delete', old.id, old.body_md, old.answer_text);
    INSERT INTO comments_fts(rowid, body_md, answer_text)
    VALUES (new.id, new.body_md, new.answer_text);
END;

-- Backfill: de prod-db heeft duizenden bestaande comments; zonder rebuild zou
-- de index alleen nieuwe comments bevatten.
INSERT INTO comments_fts(comments_fts) VALUES('rebuild');
