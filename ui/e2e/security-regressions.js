// Geïsoleerde browserfixtures; geen echte keys of productieaanroepen.
export default async function securityRegressions(page) {
  let keyExchanged = false, approved = false, policySaved = false;
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const project = {id:1,key:'SOS',name:'Audit',created_at:new Date().toISOString()};
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url());
    const path = url.pathname.replace('/api/v1','');
    let data = [];
    if (path === '/session') {
      if (request.method() === 'POST') keyExchanged = request.headers().authorization === 'Bearer lokale-testfixture';
      data = {user:{id:1,handle:'person',kind:'human'},csrf_token:'fixture-csrf',expires_at:Date.now()/1000+3600};
    } else {
      if (request.headers().authorization) throw new Error('Na uitwisseling mag geen key meegaan');
      if (!['GET','HEAD'].includes(request.method()) && request.headers()['x-csrf-token'] !== 'fixture-csrf')
        throw new Error('CSRF ontbreekt');
      if(path==='/me') data={id:1,handle:'person',display_name:'Person',kind:'human'};
      else if(path==='/users') data=[{id:1,handle:'person',display_name:'Person',kind:'human'}, {id:2,handle:'agent',display_name:'Agent',kind:'agent',active:true}];
      else if(path==='/projects') data=[project];
      else if(path.endsWith('/states')) data=[{name:'todo',group:'unstarted',is_default:true}];
      else if(path.endsWith('/state-counts')) data={todo:0};
      else if(path==='/inbox') data={items:[]};
      else if(path==='/webhook-health') data=[];
      else if(path==='/wiki-proposals') data=approved ? [] : [{id:1,slug:'policy',title:'Beleidsvoorstel',body_md:'Nieuwe regel',current_body:'Oude regel',author:'agent'}];
      else if(path==='/wiki-proposals/1/review') { approved=true; data={status:'approved'}; }
      else if(path==='/wiki') data=[{slug:'policy',title:'Beleid',body_md:approved?'Nieuwe regel':'Oude regel',protected:true,source_kind:'human'}];
      else if(path==='/wiki/index') data=[{scope:'global',slug:'policy'}];
      else if(path==='/users/agent') {
        if(request.method()==='PATCH') {
          const body=request.postDataJSON();
          policySaved=body.api_key_scopes?.includes('read') && body.api_key_projects?.includes('SOS');
        }
        data={handle:'agent',kind:'agent',api_key_scopes:['read'],api_key_projects:['SOS'],api_key_expires_at:null};
      }
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://127.0.0.1:5173/');
  await page.evaluate(()=>(localStorage.setItem('hegemone_locale','nl'), localStorage.setItem('betonning_key','lokale-testfixture')));
  await page.goto('http://127.0.0.1:5173/SOS?view=wiki');
  await page.getByText('Globaal',{exact:true}).click();
  await page.getByText('Beleidsvoorstel — van @agent',{exact:true}).click();
  await page.getByRole('button',{name:'Goedkeuren',exact:true}).click();
  await page.waitForFunction(()=>localStorage.getItem('betonning_session')==='1');
  if(!keyExchanged || !approved) throw new Error('Login of goedkeuring niet uitgevoerd');
  if(await page.evaluate(()=>localStorage.getItem('betonning_key')) !== null) throw new Error('Key bleef opgeslagen');
  await page.getByRole('button',{name:'Meer acties',exact:true}).click();
  await page.getByRole('menuitem',{name:'Agents & gebruikers',exact:true}).click();
  const buttons = page.getByRole('button',{name:/Bewerk/});
  if(await buttons.count()) await buttons.last().click();
  else await page.locator('button[title="Bewerken"]').last().click();
  await page.getByText('Sleutelrechten en vervaldatum',{exact:true}).click();
  await page.getByRole('button',{name:'Sleutelbeleid opslaan',exact:true}).click();
  if(!policySaved) throw new Error('Sleutelbeleid niet naar API verstuurd');
  for(const theme of ['light','dark']) {
    await page.emulateMedia({colorScheme:theme});
    await page.screenshot({path:`/tmp/beton-security-${theme}.png`});
  }
  await page.reload();
  await page.waitForFunction(()=>document.body.innerText.includes('Audit'));
  if(errors.length) throw new Error(errors.join('\n'));
  console.log('Browser: keymigratie, cookie/CSRF-client, herladen, kennisreview en sleutelbeleid geslaagd.');
}
