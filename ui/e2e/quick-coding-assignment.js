// BETON-507: browserregressie met geïsoleerde API-fixtures.
export default async function quickCodingAssignment(page) {
  let assignment = null, lastPatch = null, created = null;
  const settle = () => page.evaluate(async () => {
    await Promise.all(document.getAnimations()
      .filter(a => Number.isFinite(a.effect?.getComputedTiming().endTime))
      .map(a => a.finished.catch(() => {})));
  });
  const item = (ref='SOS-1') => ({ref,id:1,project:'SOS',title:'Snelle toewijzing',description_md:'Test',state:'todo',assignee:assignment,
    labels:[],comments:[],relations:{},children:[],children_detail:[],created_at:'2026-11-02T12:00:00Z',updated_at:'2026-11-02T12:00:00Z'});
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1','');
    let data=[];
    if(path==='/session') data={csrf_token:'fixture',user:{handle:'person',kind:'human'}};
    else if(path==='/me') data={id:1,handle:'person',kind:'human',display_name:'Person'};
    else if(path==='/users') data=[{handle:'person',kind:'human',display_name:'Person',active:true},
      {handle:'coding-agent',kind:'agent',is_virtual:true,active:true}, {handle:'claude',kind:'agent',active:true}];
    else if(path==='/projects') data=[{key:'SOS',name:'Testproject',triage_enabled:false}];
    else if(path.endsWith('/states')) data=[{name:'todo',group:'unstarted',is_default:true}];
    else if(path.endsWith('/state-counts')) data={todo:1};
    else if(path==='/projects/SOS/items') {
      if(request.method()==='POST') {created=request.postDataJSON();assignment=created.assignee;data=item('SOS-2');}
      else data=[item()];
    } else if(/^\/items\/SOS-[12]$/.test(path)) {
      if(request.method()==='PATCH') {lastPatch=request.postDataJSON();assignment=lastPatch.assignee;}
      data=item(path.split('/').pop());
    } else if(path.endsWith('/subscribers')) data={subscribers:[]};
    else if(path==='/inbox') data={items:[]};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://127.0.0.1:5173/');
  await page.evaluate(()=>(localStorage.setItem('hegemone_locale','nl'), localStorage.setItem('betonning_key','lokale-testfixture')));
  for(const initial of [null,'claude','person']) {
    assignment=initial; lastPatch=null;
    await page.goto('http://127.0.0.1:5173/SOS/1');
    const quick=page.getByRole('button',{name:'→ coding-agent',exact:true});
    await quick.waitFor();
    if(initial === null) {
      await settle();
      await page.screenshot({path:'/tmp/beton-507-drawer.png'});
    }
    await quick.click();
    await page.waitForFunction(()=>document.querySelector('.rail-select')?.textContent.includes('coding-agent'));
    if(lastPatch?.assignee!=='coding-agent') throw new Error('Drawer verstuurt verkeerde toewijzing');
  }
  await page.goto('http://127.0.0.1:5173/SOS');
  await page.getByRole('button',{name:'Nieuwe ticket',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Nieuw ticket',exact:true});
  const more=dialog.getByRole('button',{name:'Meer opties',exact:true});
  if(await more.getAttribute('aria-expanded')!=='false') throw new Error('Meer opties staat open');
  await dialog.getByPlaceholder('Korte omschrijving…').fill('Naar de coding-queue');
  for(const theme of ['light','dark']) {
    await page.emulateMedia({colorScheme:theme});
    await settle();
    await page.screenshot({path:`/tmp/beton-507-new-${theme}.png`});
  }
  await dialog.getByRole('button',{name:'→ coding-agent',exact:true}).click();
  if(created!==null) throw new Error('Sneltoewijzing heeft het formulier verstuurd');
  await dialog.getByRole('status').filter({hasText:'Toegewezen aan coding-agent'}).waitFor();
  if(await more.getAttribute('aria-expanded')!=='false') throw new Error('Sneltoewijzing klapt extra opties open');
  await dialog.getByRole('button',{name:'Ticket aanmaken',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  if(created?.assignee!=='coding-agent') throw new Error('Nieuw ticket mist de gekozen assignee');
  console.log('BETON-507: drawer (leeg/andere/mij) en nieuw ticket met gesloten extra opties geslaagd.');
}
