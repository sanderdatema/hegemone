// Target selection and explicit confirmation; synthetic labels and workflow only.
export default async function projectColumnSettings(page,base='http://127.0.0.1:5205') {
  let states=[],calls=[],fail=false;
  const initial=()=>[{name:'todo',group:'unstarted',color:'#3498db',item_count:2,deferred_reference_count:0},{name:'review',group:'started',color:'#9b59b6',item_count:0,deferred_reference_count:0},{name:'done',group:'completed',color:'#2ecc71',item_count:0,deferred_reference_count:0,closed:true}];
  const labels=[{name:'bug',color:'#95a5a6'},{name:'docs',color:'#95a5a6'},{name:'custom',color:'#123456'}];
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);});
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path.endsWith('/states'))data=states;else if(path.endsWith('/state-counts'))data={todo:2,review:0,done:0};
    else if(path==='/projects/DEMO/labels')data=labels;
    else if(path.endsWith('/access'))data={type_defaults:{},agents:[]};
    else if(path.startsWith('/projects/DEMO/states/') && req.method()==='DELETE'){
      calls.push({name:decodeURIComponent(path.split('/').pop()),target:url.searchParams.get('target'),count:url.searchParams.get('expected_count')});
      if(fail){fail=false;return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Count changed',error_code:'column_count_changed'})});}
      states=states.filter(s=>s.name!==calls.at(-1).name);return route.fulfill({status:204});
    }
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const lang of ['en','nl']) {
    states=initial();calls=[];await page.goto(`${base}/DEMO?language=${lang}`);
    await page.getByRole('button',{name:lang==='en'?'More actions':'Meer acties',exact:true}).click();
    await page.getByRole('menuitem',{name:lang==='en'?'Project settings':'Projectinstellingen',exact:true}).click();
    await page.locator('.st-row').first().waitFor();
    const swatches=page.locator('.chips input[type=color]');await swatches.nth(2).waitFor();
    const colors=await swatches.evaluateAll(els=>els.map(el=>el.value));
    assert(new Set(colors).size===3 && colors[2]==='#123456','Label selectors do not show resolved colors');
    assert(calls.length===0,'Opening settings wrote changes');
    await page.locator('.st-row').filter({has:page.getByRole('button',{name:'todo',exact:true})}).getByRole('button',{name:lang==='en'?'Remove':'Verwijderen',exact:true}).click();
    const confirm=page.locator('.state-delete-confirm');await confirm.waitFor();
    const action=confirm.getByRole('button',{name:lang==='en'?'Move tickets and delete':'Tickets verplaatsen en verwijderen',exact:true});
    assert(await action.isDisabled(),'Missing destination can be confirmed');
    await confirm.locator('.select-trigger').click();
    await page.getByRole('option',{name:'review',exact:true}).click();
    assert(!(await action.isDisabled()),'Valid destination still disabled');
    await confirm.getByRole('button',{name:lang==='en'?'Cancel':'Annuleren',exact:true}).click();assert(calls.length===0,'Cancel wrote deletion');
    await page.locator('.st-row').filter({has:page.getByRole('button',{name:'todo',exact:true})}).getByRole('button',{name:lang==='en'?'Remove':'Verwijderen',exact:true}).click();
    await confirm.locator('.select-trigger').click();await page.getByRole('option',{name:'review',exact:true}).click();
    fail=true;await action.click();await page.getByRole('alert').waitFor();
    assert(await confirm.count()===1,'Failure discarded selection/confirmation');
    await action.click();await confirm.waitFor({state:'detached'});
    assert(calls.length===2 && calls[1].target==='review' && calls[1].count==='2','Wrong scope/count/destination request');
    await page.setViewportSize({width:390,height:850});
    assert(await page.locator('.ps').evaluate(el=>el.scrollWidth<=el.clientWidth),'Settings overflow');
    await page.setViewportSize({width:1280,height:900});
    console.log(lang+': label colors, destination/cancel/error/retry and request count passed');
  }
}
