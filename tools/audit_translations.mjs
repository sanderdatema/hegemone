// Alleen broncode en sleutelmetadata controleren; geen gebruikersdata of omgeving.
import {readFile, readdir, writeFile} from 'node:fs/promises';
import {resolve, relative, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const {parse} = createRequire(new URL('../ui/package.json', import.meta.url))('svelte/compiler');
import {catalogs} from '../ui/src/lib/i18n.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = resolve(root, 'ui/src');
const dutch = /\b(opslaan|annuleren|verwijderen|verwijder|toevoegen|aanmaken|opgeslagen|ongelezen|toegewezen|wijzigen|gewijzigd|bewerken|bevestigen|volgende|vorige|afgerond|voorstel|reactie|antwoorden|antwoord|omschrijving|einddatum|weergave|laden|geen|zoeken|kies|selecteer|gearchiveerd|ingeklapt|archiveren|verplaatsen|verplaats|verbreek|opheffen|afwijzen|goedkeuren|volgend|vorig|sluiten|sluit|bewerk|invoegen|wissen|blijf|nee|ja|gekopieerd|subtaak|mijn|nieuw|nieuwe|alles|datum|ruimte|reviewdatum|uitstel|meldingen|tijdlijn|bijlagen|werklast|relatie|relatietype|toon|verberg|toepassen|archief|subtaken|wacht|van|werkklasse|laatst|terug|vraag|uitgesteld|reageren|aantal|huidige|vandaag|morgen|maak|taak|klein|herstellen|opknip|geselecteerd|toewijzen|archiveer|klaar|sleep|kaart|hierheen|dupliceer|beantwoord|wijzigingen|acties)\b/i;

export function literalCalls(source) {
  return [...source.matchAll(/\$(?:t|tr|uiText)\(\s*(["'])([^"']+)\1\s*(?=[,)])/g)]
    .map(match => ({key: match[2], line: source.slice(0, match.index).split('\n').length}));
}

export function fixedDutchText(source) {
  const hits = [];
  function walk(node) {
    if (!node || typeof node !== 'object' || node.type === 'Comment') return;
    // Setup/onboarding bevatten expliciete en/nl-keuzes in de template.
    if (node.type === 'ConditionalExpression' && node.test?.type === 'Identifier' && node.test.name === 'nl') return;
    const text = node.type === 'Text' ? node.data
      : node.type === 'Literal' && typeof node.value === 'string' ? node.value
      : node.type === 'TemplateElement' ? node.value.cooked : null;
    if (text && dutch.test(text)) hits.push({text: text.replace(/\s+/g,' ').trim(), line: source.slice(0,node.start).split('\n').length});
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === 'object') walk(value);
    }
  }
  // De echte parser houdt expressies en samengestelde attributen intact.
  // Script/style worden niet als zichtbare UI-tekst behandeld.
  walk(parse(source).html);
  return hits;
}

async function files(directory) {
  const result=[];
  for (const entry of await readdir(directory,{withFileTypes:true})) {
    if (entry.name.startsWith('.')) continue;
    const path=resolve(directory,entry.name);
    if(entry.isDirectory()) result.push(...await files(path));
    else if(entry.isFile() && /\.(?:svelte|js)$/.test(entry.name) && !entry.name.endsWith('.test.js') && !entry.name.endsWith('Fixture.svelte')) result.push(path);
  }
  return result;
}

async function main() {
const report={coverage:'Letterlijke vertaalaanroepen en Svelte-templateparser met NL-herkenningslijst; geen volledige taalvrijgave',calls:0,missing:[],remaining:[]};
for(const path of await files(sourceRoot)) {
  const source=await readFile(path,'utf8');
  for(const call of literalCalls(source)) {
    report.calls++;
    const absent=['en','nl'].filter(language=>!Object.hasOwn(catalogs[language],call.key));
    if(absent.length) report.missing.push({file:relative(root,path),...call,languages:absent});
  }
  if(path.endsWith('.svelte')) for(const hit of fixedDutchText(source)) report.remaining.push({file:relative(root,path),...hit});
}
const destination=process.argv[2];
if(destination) await writeFile(resolve(destination),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({calls:report.calls,missing:report.missing.length,remaining_fixed_texts:report.remaining.length}));
if(report.missing.length || report.remaining.length) process.exitCode=1;

}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
