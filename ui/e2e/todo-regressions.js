// Lokale browserregressies voor BETON-485 en BETON-488 t/m BETON-495.
// Aanroeper levert een Playwright Page in een geïsoleerde context. Alle API-antwoorden zijn fixtures.
export default async function todoRegressions(page) {

  const project = { id: 1, key: 'SOS', name: 'Proxmox homeserver — beveiliging met een zeerlangeononderbrokenprojectnaam', created_at: new Date().toISOString(), description: '', triage_enabled: false };
  const states = [{ name:'todo', group:'unstarted', color:'#3498db', is_default:true, sort_order:0 }, { name:'done', group:'completed', color:'#2ecc71', closed:true, sort_order:1 }];
  let template = states.map(s=>({...s, blocks_work:false}));
  const item = ref => ({ ref, project:'SOS', title: ref === 'SOS-1' ? 'Eerste ticket' : 'Tweede ticket', description_md: 'Omschrijving om te bewerken', state:'todo', labels:[], comments:[], relations:{}, children:[], children_detail:[], created_at: '2026-11-01T16:01:00Z', updated_at:'2026-11-01T16:02:00Z' });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname.replace('/api/v1','');
    let data = [];
    if (path === '/me') data = { handle:'person', display_name:'Person', kind:'human', id:1 };
    else if(path === '/users') data = [{ handle:'person', display_name:'Person', kind:'human', id:1 }];
    else if(path === '/projects') data = [project];
    else if(path === '/projects/SOS' && route.request().method() === 'PATCH') { Object.assign(project, route.request().postDataJSON()); data = project; }
    else if(path === '/overview') data = [{ ...project, open:2, in_progress:0, blocked:0, unassigned:2, open_questions:0, unread:0, last_activity_at:null }];
    else if(path.endsWith('/states')) data = states;
    else if(path.endsWith('/state-counts')) data = { todo:2 };
    else if(path === '/projects/SOS/items') data = [item('SOS-1'),item('SOS-2')];
    else if(path.includes('ref-candidates') || path === '/search') data = url.searchParams.get('q') === '1' ? [{ref:'SOS-1', title:'Eerste ticket'}] : [{ref:'SOS-2', title:'Tweede ticket'}];
    else if(/^\/items\/SOS-[12]$/.test(path)) { if(path.endsWith('1')) await new Promise(r=>setTimeout(r,350)); data = item(path.split('/').pop()); }
    else if(path.endsWith('/activity')) data = [];
    else if(path.endsWith('/subscribers')) data = {subscribers:[]};
    else if(path.endsWith('/access')) data = {type_defaults:{}, agents:[]};
    else if(path === '/settings/project-template') { if(route.request().method() === 'PUT') template = route.request().postDataJSON().states; data = {states:template}; }
    else if(path === '/inbox') data = { items: [{ref:'SOS-2',title:'Tweede ticket',event_id:42,reason:'mention',actor:'agent',read:false,created_at:new Date().toISOString()}] };
    else if(path === '/inbox/seen') { await new Promise(r=>setTimeout(r,2000)); data = {}; }
    await route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify(data) });
  });
  await page.goto('http://127.0.0.1:5173/');
  await page.evaluate(() => (localStorage.setItem('hegemone_locale','nl'), localStorage.setItem('betonning_key','lokale-testfixture')));
  await page.goto('http://127.0.0.1:5173/SOS');

  const assert = (ok, message) => { if(!ok) throw new Error(message); };
  const navigate = async path => {
    await page.evaluate(path => { history.pushState({}, '', path); dispatchEvent(new PopStateEvent('popstate')); }, path);
  };
  await page.waitForSelector('.card-title');
  const padding = await page.locator('.search-input').evaluate(el=>parseFloat(getComputedStyle(el).paddingLeft));
  assert(padding >= 32, 'zoektekst heeft ruimte voor icoon');
  await page.locator('.search-input').fill('voorbeeld');
  assert(await page.locator('.search-input').evaluate(el=>parseFloat(getComputedStyle(el).paddingRight)) > 140, 'ruimte voor wisknop');
  await page.locator('.search-input').fill('');
  await page.getByRole('button', {name:'Nieuwe ticket', exact:true}).click();
  const more = page.getByRole('button', {name:'Meer opties', exact:true});
  assert(await more.getAttribute('aria-expanded') === 'false', 'meer opties begint dicht');
  const desc = page.locator('textarea').first();
  await desc.fill('Hoi @per');
  await page.getByRole('option').filter({hasText:'@person'}).click();
  assert(await desc.inputValue() === 'Hoi @person ', 'mention Nieuw ticket');
  await desc.fill('Zie #2');
  await page.getByRole('option').filter({hasText:'SOS-2'}).click();
  assert(await desc.inputValue() === 'Zie SOS-2 ', 'ref Nieuw ticket');
  await more.click();
  await page.getByPlaceholder('ref of titel, bv. SOS-2').last().fill('2');
  await page.locator('#rel-suggest-new').getByRole('option').first().click();
  assert(await page.getByPlaceholder('ref of titel, bv. SOS-2').last().inputValue() === 'SOS-2', 'relatie Nieuw ticket');
  await page.screenshot({path:'/tmp/beton-todo-new.png'});
  await page.getByRole('button', {name:'Sluiten', exact:true}).click();
  await page.getByRole('button', {name:/Inbox/}).click();
  await page.locator('.group-main').click();
  await page.getByRole('dialog').filter({hasText:'Tweede ticket'}).waitFor({timeout:1500});
  await navigate('/SOS');
  await navigate('/SOS/1');
  await page.waitForTimeout(30);
  await navigate('/SOS/2');
  await page.getByText('Tweede ticket', {exact:true}).last().waitFor();
  await page.waitForTimeout(500);
  assert(await page.locator('.drawer-title').count() ? (await page.locator('.drawer-title').innerText()).includes('Tweede') : (await page.locator('[role="dialog"]').innerText()).includes('Tweede ticket'), 'nieuwe ticket wint van oude request');
  await page.getByText('Omschrijving om te bewerken', {exact:true}).click();
  const editor = page.locator('textarea').first();
  await editor.fill('@per');
  await page.getByRole('option').filter({hasText:'@person'}).click();
  assert(await editor.inputValue() === '@person ', 'mention Drawer');
  await editor.fill('#2');
  await page.getByRole('option').filter({hasText:'SOS-2'}).click();
  assert(await editor.inputValue() === 'SOS-2 ', 'ref Drawer');
  await page.getByRole('button', {name:'Relatie leggen',exact:true}).click();
  await page.locator('.rel-target').fill('1');
  await page.locator('#rel-suggest').getByRole('option').first().click();
  assert(await page.locator('.rel-target').inputValue() === 'SOS-1', 'relatie Drawer');
  await navigate('/SOS?view=overview');
  await page.waitForSelector('.ov-card-btn');
  for(const width of [1280,375]) {
    await page.setViewportSize({width,height:900});
    assert(await page.locator('.ov-card-btn').evaluate(el=>el.scrollWidth <= el.clientWidth + 1), `kaart past op ${width}`);
    await page.screenshot({path:`/tmp/beton-todo-overview-${width}.png`});
  }
  await page.emulateMedia({colorScheme:'dark'});
  await page.screenshot({path:'/tmp/beton-todo-overview-dark.png'});
  await page.setViewportSize({width:1280,height:900});
  await navigate('/SOS');
  await page.getByRole('button', {name:'Meer acties', exact:true}).click();
  await page.getByRole('menuitem', {name:'Projectinstellingen', exact:true}).click();
  await page.getByLabel('Naam van het project', {exact:true}).fill('Gewijzigde projectnaam');
  await page.getByRole('button',{name:'Naam opslaan',exact:true}).click();
  await page.getByText('Opgeslagen', {exact:true}).waitFor();
  await page.screenshot({path:'/tmp/beton-todo-settings.png'});
  await page.getByRole('button', {name:'Terug',exact:true}).click();
  await page.getByRole('button', {name:'Meer acties',exact:true}).click();
  await page.getByRole('menuitem', {name:'Projecten beheren',exact:true}).click();
  await page.getByRole('button', {name:'Nieuw project',exact:true}).click();
  await page.getByText('Projecttemplate aanpassen', {exact:true}).click();
  await page.getByLabel('Kolomnaam', {exact:true}).first().fill('Ideeën');
  const save = page.getByRole('button', {name:'Template opslaan',exact:true});
  const request = page.waitForRequest(r => r.url().endsWith('/settings/project-template') && r.method() === 'PUT');
  await save.click();
  assert((await request).postDataJSON().states[0].name === 'Ideeën', 'templatewijziging naar API');
  await page.getByText('Template opgeslagen',{exact:true}).waitFor();
  await page.screenshot({path:'/tmp/beton-todo-template-dark.png'});
  await page.emulateMedia({colorScheme:'light'});
  await page.screenshot({path:'/tmp/beton-todo-template-light.png'});
  console.log('Browserchecks geslaagd: zoekruimte, meer opties, mentions/refs/relaties, navigatierace, kaartbreedtes en projectnaam.');
}
