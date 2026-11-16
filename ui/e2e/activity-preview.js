// Readable project activity without extra per-event browser requests.
export default async function activityPreview(page,base='http://127.0.0.1:5192') {
  const title='A meaningful task title', preview='<script>not executable</script> '+ 'Preview text '.repeat(15);
  const events=[
    {id:3,type:'comment.created',actor:'builder',ref:'DEMO-1',title,comment_preview:preview,created_at:'2026-11-16T12:02:00Z',payload:{comment_id:3}},
    {id:2,type:'comment.created',actor:'builder',ref:'DEMO-1',title,comment_preview:'Older comment',created_at:'2026-11-16T12:01:00Z',payload:{comment_id:2}},
    {id:1,type:'item.updated',actor:'person',ref:'DEMO-2',title:'Another task',created_at:'2026-11-16T12:00:00Z',payload:{state:{from:'todo',to:'done'}}},
  ];
  let opened=false;
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);});
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path==='/projects/DEMO/activity')data=events;
    else if(path==='/items/DEMO-1'){opened=true;data={ref:'DEMO-1',title,state:'todo',labels:[],comments:[],children:[],relations:{}};}
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const lang of ['en','nl'])for(const width of [1280,390]) {
    await page.setViewportSize({width,height:850});
    await page.goto(`${base}/DEMO?view=activity&language=${lang}`);
    await page.locator('.activity-row').first().waitFor();
    assert(await page.locator('.activity-row').count()===2,'Existing grouping changed');
    assert((await page.locator('.activity-ticket').first().innerText()).includes(title),'Title absent');
    assert((await page.locator('.activity-count').first().innerText()).includes('2×'),'Grouped count absent');
    assert(await page.locator('.activity-preview').textContent()===preview,'Preview content lost');
    assert(await page.locator('.activity-preview script').count()===0,'Preview interpreted as markup');
    assert(await page.locator('.activity-view').evaluate(el=>el.scrollWidth<=el.clientWidth),'Activity overflows '+JSON.stringify(await page.locator('.activity-view').evaluate(el=>[el,...el.querySelectorAll('*')].filter(x=>x.scrollWidth>x.clientWidth+1).map(x=>({tag:x.tagName,cls:x.className,width:x.clientWidth,scroll:x.scrollWidth})))));
    await page.locator('.activity-line').first().focus();await page.keyboard.press('Enter');
    await page.locator('.drawer-dialog').waitFor();assert(opened,'Ticket did not open');
    await page.keyboard.press('Escape');await page.locator('.drawer-dialog').waitFor({state:'detached'});
  }
}
