// Choosing an assignee is a draft change, never an implicit creation or run.
export default async function assignmentChoice(page,base='http://127.0.0.1:5192') {
  let triage=false;const writes=[];
  const roster=[{handle:'coding-agent',display_name:'Coding queue',kind:'agent',agent_type:'coding',is_virtual:true,active:true},{handle:'builder',display_name:'Builder',kind:'agent',agent_type:'coding',active:true}];
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);});
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo',triage_enabled:triage}];
    else if(path==='/users')data=roster;
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted',is_default:true}];
    else if(path.endsWith('/state-counts'))data={todo:0};
    else if(path==='/projects/DEMO/items' && req.method()==='POST'){const body=req.postDataJSON();writes.push(body);data={...body,ref:'DEMO-1',project:'DEMO',state:'todo',labels:[]};}
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const lang of ['en','nl'])for(const enabled of [false,true]) {
    triage=enabled;
    await page.goto(`${base}/DEMO?language=${lang}`);
    await page.evaluate(()=>localStorage.setItem('hegemone_quick_assignment:person',JSON.stringify(['coding-agent','builder'])));
    await page.locator('.tb-new').click();
    const modal=page.getByRole('dialog');
    const before=writes.length;
    await modal.getByRole('button',{name:lang==='en'?'Choose queue @coding-agent':'Kies wachtrij @coding-agent',exact:true}).click();
    assert(writes.length===before,'Choosing queue created ticket');
    assert((await modal.locator('.assignment-choice').innerText()).includes('coding-agent'),'Queue selection not explicit');
    await modal.getByRole('button',{name:lang==='en'?'Choose @builder':'Kies @builder',exact:true}).click();
    assert((await modal.locator('.assignment-choice').innerText()).includes('@builder'),'Individual selection not explicit');
    assert(writes.length===before,'Choosing individual created ticket');
    const hint=await modal.locator('p.hint.muted').innerText();
    assert(enabled ? hint.includes(lang==='en'?'Triage fills':'Triage vult') : hint.includes(lang==='en'?'triage is off':'triage staat uit'),'Triage explanation incorrect');
    await modal.getByPlaceholder(lang==='en'?'Short description…':'Korte omschrijving…').fill('Synthetic task');
    await modal.getByRole('button',{name:lang==='en'?'Create ticket':'Ticket aanmaken',exact:true}).click();
    await modal.waitFor({state:'detached'});
    assert(writes.length===before+1 && writes.at(-1).assignee==='builder','Creation count or destination wrong');
    await page.evaluate(()=>localStorage.setItem('hegemone_quick_assignment:person','[]'));
    await page.locator('.tb-new').click();
    assert(await page.locator('.quick-assign').count()===0,'Empty preference ignored');
    await page.keyboard.press('Escape');
  }
}
