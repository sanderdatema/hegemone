import {it, expect} from 'vitest';
import {fixedDutchText} from '../../tools/audit_translations.mjs';

it('vindt Nederlandse tekst naast expressies, in attributen en template literals', () => {
  const hits = fixedDutchText('<script>const label = "Geen";</script><button title="Selecteer alles in {column}" aria-label={`Nieuw ticket in ${column}`}>{count} subtaken</button>');
  expect(hits.map(hit => hit.text)).toEqual(['Selecteer alles in', 'Nieuw ticket in', 'subtaken']);
});

it('negeert comments, scriptlogica en expliciete tweetalige onboardingkeuzes', () => {
  expect(fixedDutchText('<script>const value = "Geen";</script><!-- Geen --><h1>{nl ? "Maak een project" : "Create a project"}</h1><p>Label</p>')).toEqual([]);
});
