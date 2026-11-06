-- BETON-218: apart plan-veld op items. Een zwaar model zet er een gedetailleerd
-- plan/handover in; een lichter model voert het uit. Bewust een los veld naast
-- description_md zodat een groot plan de omschrijving/comments niet vult, en
-- bewust NIET in de standaard-serialisatie (token-economie: alleen on-demand
-- via GET /items/{ref}/plan; de detail-representatie adverteert `has_plan`).
ALTER TABLE items ADD COLUMN plan_md TEXT;
