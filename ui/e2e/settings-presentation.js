// Preferences, hidden inactive users and explicit integration actions.
export default async function settingsPresentation(page,base='http://127.0.0.1:5192') {
  const me={id:1,handle:'person',display_name:'Person',kind:'human',active:true,credential_policy:{scopes:['read','write','admin','llm']}};
  let inactive={id:3,handle:'inactive',display_name:'Inactive agent',kind:'agent',active:false,agent_type:'coding'};
  const receiver={id:2,handle:'receiver',display_name:'Receiver',kind:'agent',active:true,agent_type:'hermes',has_webhook:true};
  let preferences={subscribe_all:false,description:'',webhook_url:null,telegram_chat_id:null,has_webhook_secret:false};
  let saves=0,tests=0;
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);});
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic',user:me};
    else if(path==='/me')data=me;
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path==='/users')data=[inactive,receiver,me];
    else if(path==='/users/inactive' && req.method()==='PATCH'){inactive={...inactive,...req.postDataJSON()};data=inactive;}
    else if(path==='/users/me/settings'){if(req.method()==='PATCH'){saves++;preferences={...preferences,...req.postDataJSON()};}data=preferences;}
    else if(path==='/settings/model-classes')data={classes:[],mapping:{}};
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path.endsWith('/state-counts'))data={todo:0};
    else if(path==='/users/receiver/webhook-test'){tests++;data={id:1,status:'pending',attempts:0};return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify(data)});}
    else if(path==='/users/receiver/webhook-test/1')data={id:1,status:'delivered',attempts:1,http_status:200};
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const lang of ['en','nl']) {
    inactive.active=false;preferences.subscribe_all=false;
    await page.setViewportSize({width:1280,height:900});await page.goto(`${base}/DEMO?language=${lang}`);
    await page.getByRole('button',{name:'Account (@person)',exact:true}).click();
    await page.getByRole('menuitem',{name:lang==='en'?'My settings':'Mijn instellingen',exact:true}).click();
    const panel=page.locator('.us');await panel.locator('.us-advanced').waitFor();
    assert(await panel.locator('.us-advanced').getAttribute('open')===null,'Advanced settings expanded by default');
    const quick=panel.locator('[aria-label="'+(lang==='en'?'Quick assignment buttons':'Knoppen voor snel toewijzen')+'"]');
    assert((await quick.boundingBox()).y < (await panel.locator('.us-advanced').boundingBox()).y,'Daily preference after integrations');
    const before=saves;await quick.getByRole('checkbox').first().check();assert(saves===before,'Quick preference unexpectedly saved server fields');
    await panel.getByRole('switch',{name:lang==='en'?'Follow all tickets':'Alles volgen',exact:true}).click();assert(saves===before,'Follow toggle saved before explicit save');
    await panel.getByRole('button',{name:lang==='en'?'Save':'Opslaan',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.us-ok'));
    assert(saves===before+1 && preferences.subscribe_all,'Explicit save lost');
    await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:lang==='en'?'More actions':'Meer acties',exact:true}).click();
    await page.getByRole('menuitem',{name:lang==='en'?'Agents & users':'Agents & gebruikers',exact:true}).click();
    await page.locator('.ag-item').first().waitFor();assert(await page.locator('.ag-item.inactive').count()===0,'Inactive agents not collapsed');
    const initialTests=tests;
    await page.locator('.inactive-toggle').click();
    const inactiveRow=page.locator('.ag-item.inactive');await inactiveRow.locator('.ag-actions summary').click();
    await inactiveRow.getByRole('button',{name:lang==='en'?'Reactivate':'Heractiveren',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.ag-item.inactive').length===0);
    assert(inactive.active,'Reactivation not preserved');
    const row=page.locator('.ag-item').filter({has:page.locator('.ag-handle',{hasText:'@receiver'})});
    assert(await row.locator('.ag-webhook-details').getAttribute('open')===null,'Webhook explanation not collapsed');
    await row.locator('.ag-webhook-details summary').click();assert(tests===initialTests,'Opening test details sent a request');
    await row.getByRole('button',{name:lang==='en'?'Test saved webhook':'Opgeslagen webhook testen',exact:true}).click();
    await row.locator('[role=status]').filter({hasText:lang==='en'?'Test delivered successfully':'Test succesvol afgeleverd'}).waitFor();
    await row.getByRole('button',{name:lang==='en'?'Refresh test status':'Teststatus verversen',exact:true}).click();
    assert(tests===initialTests+1,'Status refresh repeated test');
    await page.setViewportSize({width:390,height:844});await row.locator('.ag-actions summary').click();
    assert(await page.locator('.ag').evaluate(el=>el.scrollWidth<=el.clientWidth),'Agent controls overflow');
    await page.keyboard.press('Escape');
  }
}
