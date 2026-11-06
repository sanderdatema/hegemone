// Synthetische browsercontrole van kaart-/bulklabels; geen echte API of credentials.
export default async function workviewLanguage(page, base='http://127.0.0.1:8149') {
  const user={id:1,handle:'operator',display_name:'Operator',kind:'human',active:true};
  const item={id:1,ref:'TEAM-1',project:'TEAM',title:'Original title',state:'Todo',priority:'none',workload:'small',labels:['routine'],assignee:null,created_at:'2026-11-01T12:00:00Z',last_activity_at:'2026-11-01T12:00:00Z',children_done:1,children_total:3,deferred_until:'2026-12-01',locked:true,has_guardrail:true,has_open_question:true};
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');
    let data=[];
    if(path==='/setup') data={required:false,enabled:false};
    else if(path==='/session') data={csrf_token:'fixture',user};
    else if(path==='/me') data=user;
    else if(path==='/onboarding') data={required:false,step:'complete',locale:'en'};
    else if(path==='/projects') data=[{key:'TEAM',name:'Team'}];
    else if(path==='/users') data=[user];
    else if(path.endsWith('/states')) data=[{name:'Todo',group:'unstarted'},{name:'Done',group:'completed',closed:true}];
    else if(path.endsWith('/state-counts')) data={Todo:1,Done:0};
    else if(path.endsWith('/labels')) data=[{name:'routine'}];
    else if(path.endsWith('/items')) data=[item];
    else if(path==='/inbox') data={items:[],unread:0};
    if(path==='/events/stream') return route.fulfill({status:200,contentType:'text/event-stream',body:': heartbeat\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.addInitScript(()=>{localStorage.setItem('betonning_key','synthetic-browser-fixture');localStorage.setItem('hegemone_locale','en');});
  await page.goto(base);
  await page.getByText('Original title',{exact:true}).waitFor();
  await page.getByTitle('Locked: agents stop responding',{exact:true}).waitFor();
  await page.getByTitle('1 of 3 subtasks completed',{exact:true}).waitFor();
  await page.getByText('1/3 subtasks',{exact:true}).waitFor();
  await page.getByTitle('Deferred until 2026-12-01',{exact:true}).waitFor();
  await page.getByRole('button',{name:'More actions',exact:true}).click();
  await page.getByRole('menuitem',{name:'Select multiple',exact:true}).click();
  await page.getByRole('region',{name:'Bulk actions',exact:true}).waitFor();
  await page.getByRole('button',{name:'Select all in Todo',exact:true}).click();
  await page.getByText('1 selected',{exact:true}).waitFor();
  await page.screenshot({path:'/tmp/hegemone-workview-english.png'});
  await page.getByRole('button',{name:'Account (@operator)',exact:true}).click();
  await page.getByRole('menuitem',{name:'Nederlands',exact:true}).click();
  await page.keyboard.press('Escape');
  await page.getByRole('region',{name:'Bulk-acties',exact:true}).waitFor();
  await page.getByText('1 geselecteerd',{exact:true}).waitFor();
  await page.getByTitle('1 van 3 subtaken afgerond',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Selecteer alles in Todo',exact:true}).waitFor();
  await page.getByText('Original title',{exact:true}).waitFor();
  await page.screenshot({path:'/tmp/hegemone-workview-dutch.png'});
}
