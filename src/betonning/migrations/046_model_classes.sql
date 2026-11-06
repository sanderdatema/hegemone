-- BETON-476: drie werkklassen (routine / standaard / complex) vervangen de
-- modellabels opus/sonnet/gpt-*. Per harnas (claude, codex, ...) zet de mens
-- globaal welk model bij welke klasse hoort. Nieuwe tabel, geen bestaande
-- tabellen geraakt.
CREATE TABLE model_classes (
    harness TEXT NOT NULL,
    class   TEXT NOT NULL CHECK (class IN ('routine', 'standaard', 'complex')),
    model   TEXT NOT NULL,
    PRIMARY KEY (harness, class)
);

INSERT INTO model_classes (harness, class, model) VALUES
    ('claude', 'routine',   'sonnet'),
    ('claude', 'standaard', 'sonnet'),
    ('claude', 'complex',   'opus'),
    ('codex',  'routine',   'gpt-5.4-mini'),
    ('codex',  'standaard', 'gpt-5.5'),
    ('codex',  'complex',   'gpt-5.5');
