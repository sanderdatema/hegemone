// Open/all list scope, history restoration and readable ownership.
export default async function listScope(page, base='http://127.0.0.1:5192') {
  const states=[{name:'Ready',group:'unstarted'},{name:'Released',group:'completed',closed:true},{name:'Dropped',group:'cancelled',closed:true}];
  const items=states.map((state,i)=>({ref:`DEMO-${i+1}`,project:'DEMO',title:`Example ${i+1}`,state:state.name,assignee:'coding-agent',labels:[],comments:[],children:[],relations:{}}));
  await page.addInitScript(()=>{
    localStorage.setItem('betonning_session','1');
    const language=new URLSearchParams(location.search).get('language');
    if(language)localStorage.setItem('hegemone_locale',language);
  });
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path.endsWith('/states'))data=states;
    else if(path.endsWith('/state-counts'))data={Ready:1,Released:1,Dropped:1};
    else if(path==='/projects/DEMO/items')data=items;
    else if(path.startsWith('/items/DEMO-'))data=items.find(x=>path.endsWith(x.ref));
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const language of ['en','nl'])for(const width of [1280,1920]) {
    await page.setViewportSize({width,height:800});
    await page.goto(`${base}/DEMO?view=list&listScope=all&language=${language}`);
    await page.locator('.list-row').nth(2).waitFor();
    assert(await page.locator('.assignee-handle').first().evaluate(el=>el.scrollWidth<=el.clientWidth),'Queue handle is truncated');
    const scope=page.locator('.list-toolbar .segmented');
    await scope.getByRole('radio',{name:'Open',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.list-row').length===1);
    assert(new URL(page.url()).searchParams.get('listScope')==='open','Scope not in URL');
    await page.reload();await page.locator('.list-row').waitFor();
    assert(await page.locator('.list-row').count()===1,'Reload lost scope');
    await page.locator('.title-open').click();await page.locator('.drawer-dialog').waitFor();
    await page.goBack();await page.locator('.drawer-dialog').waitFor({state:'detached'});
    assert(await page.locator('.list-row').count()===1,'Back lost scope');
    await scope.getByRole('radio',{name:language==='en'?'All':'Alles',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.list-row').length===3);
    await page.goto(`${base}/DEMO?view=list&language=${language}`);await page.locator('.list-row').nth(2).waitFor();
    assert(await page.locator('.list-row').count()===3,'Persisted all choice lost');
  }
}
