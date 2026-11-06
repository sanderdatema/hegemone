-- BETON-311: prioriteit vervangen door werklast (hoeveel werk/tokens een ticket
-- oplevert). Drie categorieën: light/medium/heavy (UI toont licht/middel/zwaar).
--
-- Nullable, GEEN default: een lege waarde betekent "nog niet geschat" — dat is
-- het signaal waarop triage bijspringt (fase 3). Een non-null default zou dat
-- signaal wegnemen (triage kan een echte schatting dan niet van de default
-- onderscheiden), dus bewust NULL.
--
-- De oude `priority`-kolom blijft bestaan voor databasecompatibiliteit — een DROP COLUMN op bestaande gegevens is
-- onnodig risico. Fase 1 is puur additief: workload komt erbij, priority
-- verdwijnt pas uit de API/MCP/UI-surface in fase 2 (samen met de UI-swap),
-- zodat elke commit een werkend systeem oplevert.
--
-- CHECK mag bij ADD COLUMN (kolom-CHECK, verwijst alleen naar de nieuwe kolom);
-- `NULL IN (...)` is NULL, niet false, dus de lege waarde passeert de CHECK.
-- ADD COLUMN (geen table-recreate) draait zo ook op een gevulde prod-db.
ALTER TABLE items ADD COLUMN workload TEXT
    CHECK (workload IN ('light', 'medium', 'heavy'));
