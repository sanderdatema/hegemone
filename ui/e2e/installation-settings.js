// Beheerflow met uitsluitend synthetische API-fixtures; geen echte provider.
export default async function installationSettings(page, base = 'http://127.0.0.1:8155') {
  const key = 'synthetic-provider-browser-key';
  let testCalls = 0, writes = 0, conflictNext = false, failTest = false;
  const provider = () => ({enabled:false,base_url:'',model:'',timeout:30,has_api_key:false});
  let data = {schema_version:1,revision:0,secret_storage_ready:true,settings:{public_url:'http://localhost:8000',language:'en',ai_language:'en',triage_enabled:false,wiki_compile_enabled:false,llm:provider(),embedding:provider()},runtime:{overrides:[],providers:{llm:{enabled:false,ready:false,source:'stored',overrides:[]},embedding:{enabled:false,ready:false,source:'stored',overrides:[]}}}};
  const user = {id:1,handle:'operator',display_name:'Operator',kind:'human',active:true,credential_policy:{scopes:['read','write','admin','llm']}};
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1','');
    const method=route.request().method(); let body=[];
    if(path==='/setup') body={required:false,enabled:false};
    else if(path==='/session') body={csrf_token:'fixture',user};
    else if(path==='/me') body=user;
    else if(path==='/onboarding') body={required:false,step:'complete',locale:'en'};
    else if(path==='/projects') body=[{key:'TEAM',name:'Team'}];
    else if(path==='/users') body=[user];
    else if(path.endsWith('/states')) body=[{name:'todo',group:'unstarted'}];
    else if(path.endsWith('/state-counts')) body={todo:0};
    else if(path==='/inbox') body={items:[],unread:0};
    else if(path==='/settings/installation') {
      if(method==='PATCH') {
        if(conflictNext) {
          conflictNext=false;
          return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Installatie-instellingen zijn intussen gewijzigd; laad ze opnieuw',error_code:'installation_revision_conflict'})});
        }
        const update=route.request().postDataJSON();
        if(update.expected_revision!==data.revision) throw new Error('Verkeerde revisie');
        writes++;
        for(const [field,value] of Object.entries(update.settings)) {
          if(field==='llm'||field==='embedding') {
            const {api_key,...publicValues}=value;
            Object.assign(data.settings[field],publicValues);
            if(Object.hasOwn(value,'api_key')) data.settings[field].has_api_key=!!api_key;
          } else data.settings[field]=value;
        }
        data.revision++;
        for(const name of ['llm','embedding']) data.runtime.providers[name]={enabled:data.settings[name].enabled,ready:!!(data.settings[name].enabled&&data.settings[name].has_api_key&&data.settings[name].model&&data.settings[name].base_url),source:'stored',overrides:[]};
      }
      body=data;
    } else if(path.endsWith('/providers/llm/test')) {
      testCalls++;
      if(failTest) { failTest=false; return route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({detail:'Do not show '+key})}); }
      body={ok:true,provider:'llm',runtime_revision:data.revision,duration_ms:1};
    }
    if(path==='/events/stream') return route.fulfill({status:200,contentType:'text/event-stream',body:': heartbeat\n\n'});
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.addInitScript(() => {localStorage.setItem('betonning_key','synthetic-browser-login-key');localStorage.setItem('hegemone_locale','en');});
  await page.goto(base);
  await page.getByRole('button',{name:'More actions',exact:true}).click();
  await page.getByRole('menuitem',{name:'Installation settings',exact:true}).click();
  await page.locator('.installation-settings').getByRole('heading',{name:'Installation settings',exact:true}).waitFor();
  const group=page.getByRole('group',{name:'Language model provider',exact:true});
  if(testCalls) throw new Error('Test startte automatisch');
  await group.getByLabel('Enable provider',{exact:true}).check();
  await group.getByLabel('API base URL',{exact:true}).fill('https://provider.example/v1');
  await group.getByLabel('Model',{exact:true}).fill('browser-model');
  await group.getByLabel('New API key',{exact:true}).fill(key);
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByText('Settings saved and applied',{exact:true}).waitFor();
  if(await group.getByLabel('New API key',{exact:true}).inputValue()) throw new Error('Keyinvoer bleef gevuld');
  const stored=await page.evaluate(value=>Object.values(localStorage).concat(Object.values(sessionStorage)).some(entry=>entry.includes(value)),key);
  if(stored) throw new Error('Providerkey in browserstorage');
  await group.getByRole('button',{name:'Test saved connection',exact:true}).click();
  await group.getByText('Connection test succeeded',{exact:true}).waitFor();
  if(testCalls!==1||writes!==1) throw new Error('Onverwachte test-/schrijfactie');
  failTest=true;
  await group.getByRole('button',{name:'Test saved connection',exact:true}).click();
  await group.getByText('Connection test failed. Check the saved settings and try again.',{exact:true}).waitFor();
  if((await page.locator('body').innerText()).includes(key)) throw new Error('Ruwe testfout zichtbaar');
  await group.getByLabel('Model',{exact:true}).fill('not-saved');
  if(await group.getByRole('button',{name:'Test saved connection',exact:true}).isEnabled()) throw new Error('Test beschikbaar met onbewaarde wijzigingen');
  await page.getByRole('button',{name:'Reload saved settings',exact:true}).click();
  await page.getByRole('button',{name:'Discard and reload',exact:true}).click();
  await group.getByLabel('Model',{exact:true}).waitFor();
  if(await group.getByLabel('Model',{exact:true}).inputValue()!=='browser-model') throw new Error('Herladen herstelde model niet');
  conflictNext=true;
  await group.getByLabel('Model',{exact:true}).fill('conflicting-model');
  await group.getByLabel('New API key',{exact:true}).fill(key);
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByText(/Installation settings have changed/).waitFor();
  if(await group.getByLabel('New API key',{exact:true}).inputValue()) throw new Error('Keyinvoer bleef gevuld na fout');
  if(await group.getByLabel('Model',{exact:true}).inputValue()!=='conflicting-model') throw new Error('Concept kwijt na conflict');
  await page.getByRole('button',{name:'Reload saved settings',exact:true}).click();
  await page.getByRole('button',{name:'Discard and reload',exact:true}).click();
  await page.screenshot({animations:'disabled',path:'/tmp/hegemone-installation-settings-light.png'});
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await page.getByRole('button',{name:'Account (@operator)',exact:true}).click();
  await page.getByRole('menuitem',{name:/Nederlands/}).click();
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Meer acties',exact:true}).click();
  await page.getByRole('menuitem',{name:'Installatie-instellingen',exact:true}).click();
  await page.locator('.installation-settings').getByRole('heading',{name:'Installatie-instellingen',exact:true}).waitFor();
  await page.getByText('Geconfigureerd — verbinding niet getest',{exact:true}).waitFor();
  const dutch=page.getByRole('group',{name:'Taalmodelprovider',exact:true});
  await dutch.getByLabel('Opgeslagen key verwijderen',{exact:true}).check();
  await page.getByRole('button',{name:'Wijzigingen bewaren',exact:true}).click();
  await page.getByText('Instellingen bewaard en toegepast',{exact:true}).waitFor();
  await dutch.getByText('Geen key opgeslagen',{exact:true}).waitFor();
  if(await dutch.getByRole('button',{name:'Opgeslagen verbinding testen',exact:true}).isEnabled()) throw new Error('Test beschikbaar na keyverwijdering');
  if(writes!==2||testCalls!==2) throw new Error('Onverwachte extra acties');
  await page.emulateMedia({colorScheme:'dark'});
  await page.screenshot({animations:'disabled',path:'/tmp/hegemone-installation-settings-dark.png'});
}
