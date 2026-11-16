// Factual board summaries and relation navigation, using synthetic records.
export default async function itemActions(page,base='http://127.0.0.1:5192') {
  const items=[
    {ref:'DEMO-1',title:'Decision',has_open_question:true,work_signals:{question_for_viewer:true}},
    {ref:'DEMO-2',title:'Blocked task',relations:{blocked_by:['DEMO-3'],relates_to:['DEMO-1']},work_signals:{blocked_by:['DEMO-3']}},
    {ref:'DEMO-3',title:'Queued task',assignee:'coding-agent'},
    {ref:'DEMO-4',title:'Delivery only',last_delivery_at:'2026-11-01'},
  ].map(item=>({state:'todo',labels:[],project:'DEMO',comments:[],children:[],relations:{},...item}));
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);});
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path==='/users')data=[{handle:'coding-agent',display_name:'Coding queue',kind:'agent',is_virtual:true,active:true}];
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path.endsWith('/state-counts'))data={todo:4};
    else if(path==='/projects/DEMO/items')data=items;
    else if(path.startsWith('/items/DEMO-'))data=items.find(x=>path.endsWith(x.ref))||items[0];
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const lang of ['en','nl']) {
    await page.goto(`${base}/DEMO?view=board&language=${lang}`);
    await page.locator('.card').first().waitFor();
    const decision=page.locator('.card[data-ref="DEMO-1"]');
    assert((await decision.innerText()).includes(lang==='en'?'Waiting for your answer':'Wacht op jouw antwoord'),'Directed question absent');
    const blocked=page.locator('.card[data-ref="DEMO-2"]');
    assert((await blocked.innerText()).includes(lang==='en'?'Blocked by DEMO-3':'Geblokkeerd door DEMO-3'),'Blocker absent');
    assert((await page.locator('.card[data-ref="DEMO-3"]').innerText()).includes('@coding-agent'),'Queue absent');
    assert(await page.locator('.card[data-ref="DEMO-4"] .item-action').count()===0,'Delivery falsely implies execution');
    await blocked.getByRole('button',{name:lang==='en'?'1 other relations':'1 overige relaties',exact:true}).click();
    await page.locator('.drawer-dialog').waitFor();
    assert((await page.locator('.dw-title-area').innerText()).includes(lang==='en'?'Blocked by DEMO-3':'Geblokkeerd door DEMO-3'),'Drawer summary absent');
    await page.keyboard.press('Escape');await page.locator('.drawer-dialog').waitFor({state:'detached'});
    await blocked.locator('.card-rel').first().click();
    await page.locator('.dw-title').filter({hasText:'Queued task'}).waitFor();
    await page.keyboard.press('Escape');
  }
}
