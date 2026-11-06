// Configuratieoverdracht met synthetische fixtures en zonder echte API-mutaties.
export default async function configurationTransfer(page, base='http://127.0.0.1:8162') {
  const token='synthetic-configuration-preview-token-0000000000';
  let previews=0, confirmations=0, applied=0, staged=null, stale=false;
  const provider=()=>({enabled:false,base_url:'',model:'',timeout:30});
  let doc={format:'hegemone.configuration',version:1,installation:{public_url:'http://localhost:8000',language:'en',ai_language:'en',triage_enabled:false,wiki_compile_enabled:false,llm:provider(),embedding:provider()},model_classes:{},project_template:[{name:'todo',group:'unstarted',color:'#3498db',is_default:true,closed:false,blocks_work:false}],agents:[],projects:[]};
  const user={id:1,handle:'operator',display_name:'Operator',kind:'human',active:true,credential_policy:{scopes:['read','write','admin','llm']}};
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={required:false,enabled:false};
    else if(path==='/session')data={user,csrf_token:'fixture'};
    else if(path==='/me')data=user;
    else if(path==='/onboarding')data={required:false,step:'complete',locale:'en'};
    else if(path==='/users')data=[user];
    else if(path==='/projects')data=[{key:'TEAM',name:'Team'}];
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path.endsWith('/state-counts'))data={todo:0};
    else if(path==='/inbox')data={items:[],unread:0};
    else if(path==='/settings/installation')data={schema_version:1,revision:applied,secret_storage_ready:true,settings:{...doc.installation,llm:{...doc.installation.llm,has_api_key:false},embedding:{...doc.installation.embedding,has_api_key:false}},runtime:{providers:{llm:{enabled:false,ready:false,source:'stored',overrides:[]},embedding:{enabled:false,ready:false,source:'stored',overrides:[]}},overrides:[]}};
    else if(path==='/settings/configuration/export')data=doc;
    else if(path==='/settings/configuration/preview'){
      previews++;staged=route.request().postDataJSON();
      data={preview_token:token,expires_at:staged.installation.public_url==='https://expired.example'?'2000-01-01T00:00:00Z':'2099-01-01T00:00:00Z',can_apply:!staged.projects.length,changes:[{resource:'installation',identity:'installation',action:'update',before:doc.installation,after:staged.installation}],conflicts:staged.projects.length?[{code:'unknown_agent',target:'missing-agent'}]:[],warnings:[]};
    }else if(path==='/settings/configuration/confirm'){
      confirmations++;const payload=route.request().postDataJSON();
      if(payload.preview_token!==token||payload.confirmed!==true)throw new Error('Verkeerde bevestiging');
      if(stale){stale=false;return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Configuratie is gewijzigd; maak een nieuwe importpreview',error_code:'configuration_changed'})});}
      doc=staged;applied++;data={applied:true,changes:1,revision:applied};
    }
    if(path==='/events/stream')return route.fulfill({status:200,contentType:'text/event-stream',body:': heartbeat\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.addInitScript(()=>{localStorage.setItem('betonning_key','synthetic-configuration-login');localStorage.setItem('hegemone_locale','en');});
  await page.goto(base);
  await page.getByRole('button',{name:'More actions',exact:true}).click();
  await page.getByRole('menuitem',{name:'Installation settings',exact:true}).click();
  const panel=page.locator('.configuration-transfer');
  await panel.getByRole('heading',{name:'Import and export',exact:true}).waitFor();
  const downloading=page.waitForEvent('download');
  await panel.getByRole('button',{name:'Download saved configuration',exact:true}).click();
  const downloaded=await downloading;
  if(downloaded.suggestedFilename()!=='hegemone-configuration-v1.json')throw new Error('Onjuist downloadformaat');
  await downloaded.saveAs('/tmp/hegemone-configuration-browser.json');
  const input=panel.getByLabel('Configuration file',{exact:true});
  const upload=async(value,name='config.json')=>{
    await page.waitForFunction(()=>{const input=document.querySelector('.configuration-transfer input[type=file]');return input&&!input.disabled;});
    await input.setInputFiles({name,mimeType:'application/json',buffer:Buffer.from(typeof value==='string'?value:JSON.stringify(value))});
  };
  await upload('{"key":"synthetic-private-value"','invalid.json');
  await panel.getByText('Choose a valid Hegemone version 1 configuration file.',{exact:true}).waitFor();
  if(previews||(await panel.innerText()).includes('synthetic-private-value'))throw new Error('Ongeldige invoer doorgestuurd of getoond');
  const incoming=structuredClone(doc);incoming.installation.language='nl';
  await upload(incoming);
  await panel.getByText('Nothing has been applied. Review every change before confirming.',{exact:true}).waitFor();
  await panel.locator('summary').click();
  if(!(await panel.innerText()).includes('"language": "nl"')||(await panel.innerText()).includes(token))throw new Error('Preview onjuist of token zichtbaar');
  if(await page.evaluate(value=>Object.values(localStorage).concat(Object.values(sessionStorage)).some(entry=>entry.includes(value)),token))throw new Error('Token in browserstorage');
  await panel.getByRole('button',{name:'Apply configuration…',exact:true}).click();
  if(confirmations)throw new Error('Toegepast vóór bevestiging');
  await panel.getByRole('button',{name:'Yes, apply configuration',exact:true}).click();
  await panel.getByText('Configuration imported',{exact:true}).waitFor();
  if(applied!==1||confirmations!==1)throw new Error('Onjuiste importtelling');
  const conflict=structuredClone(doc);conflict.projects=[{key:'TEAM',name:'Team',triage_enabled:false,wiki_compile_enabled:false,type_defaults:{},agent_overrides:{'missing-agent':'assign'}}];
  await upload(conflict);
  await panel.getByText('Resolve these conflicts first',{exact:true}).waitFor();
  if(await panel.getByRole('button',{name:'Apply configuration…',exact:true}).isEnabled())throw new Error('Conflict kan toegepast worden');
  await panel.getByRole('button',{name:'Discard preview',exact:true}).click();
  const expired=structuredClone(doc);expired.installation.public_url='https://expired.example';
  await upload(expired);
  await panel.getByText('This preview has expired. Select the file again for a new preview.',{exact:true}).waitFor();
  if(await panel.getByRole('button',{name:'Apply configuration…',exact:true}).isEnabled())throw new Error('Verlopen preview kan toegepast worden');
  await panel.getByRole('button',{name:'Discard preview',exact:true}).click();
  const changed=structuredClone(doc);changed.installation.language='en';
  await upload(changed);
  await panel.getByRole('button',{name:'Apply configuration…',exact:true}).click();stale=true;
  await panel.getByRole('button',{name:'Yes, apply configuration',exact:true}).click();
  await panel.getByText(/Configuration has changed/).waitFor();
  const url=page.getByLabel('Public URL',{exact:true});await url.fill('https://draft.example');
  if(await input.isEnabled())throw new Error('Import mogelijk met onbewaarde instellingen');
  await url.fill(doc.installation.public_url);
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await page.getByRole('button',{name:'Account (@operator)',exact:true}).click();
  await page.getByRole('menuitem',{name:/Nederlands/}).click();await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Meer acties',exact:true}).click();
  await page.getByRole('menuitem',{name:'Installatie-instellingen',exact:true}).click();
  await panel.getByRole('heading',{name:'Importeren en exporteren',exact:true}).waitFor();
  await panel.getByLabel('Configuratiebestand',{exact:true}).setInputFiles({name:'voorbeeld.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(changed))});
  await panel.getByText('Er is nog niets toegepast. Controleer alle wijzigingen vóór bevestiging.',{exact:true}).waitFor();
  await panel.locator('summary').click();
  await panel.screenshot({path:'/tmp/hegemone-configuration-transfer-nl.png',animations:'disabled'});
  await panel.getByRole('button',{name:'Preview weggooien',exact:true}).click();
  if(confirmations!==2||applied!==1)throw new Error('Onverwachte herhaling of extra import');
}
