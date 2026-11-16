// Native selection semantics and readable metadata in both color schemes.
export default async function selectionAccessibility(page, base='http://127.0.0.1:5192') {
  const items=[1,2].map(i=>({ref:`DEMO-${i}`,project:'DEMO',title:`Example ${i}`,state:'todo',labels:[],last_activity_at:'2026-11-01T12:00:00Z'}));
  await page.addInitScript(()=>{
    localStorage.setItem('betonning_session','1');
    localStorage.setItem('hegemone_locale',new URLSearchParams(location.search).get('language')||'en');
  });
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');
    let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Demo'}];
    else if(path.endsWith('/states'))data=[{name:'todo',closed:false,group:'unstarted'}];
    else if(path.endsWith('/state-counts'))data={todo:2};
    else if(path==='/projects/DEMO/items')data=items;
    else if(path==='/items/DEMO-1')data={...items[0],comments:[],children:[],relations:{}};
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  for(const language of ['en','nl'])for(const view of ['board','list']) {
    await page.goto(`${base}/DEMO?view=${view}&language=${language}`);
    await page.getByText('Example 1',{exact:true}).waitFor();
    if(view==='list') {
      assert(await page.getByRole('row').count()===3,'Table row semantics missing');
      await page.locator('.title-open').first().focus();
      await page.keyboard.press('Enter');
      await page.locator('.drawer-dialog').waitFor();
      await page.keyboard.press('Escape');
      await page.locator('.drawer-dialog').waitFor({state:'detached'});
    }
    await page.getByRole('button',{name:language==='en'?'More actions':'Meer acties',exact:true}).click();
    await page.getByRole('menuitem',{name:language==='en'?'Select multiple':'Meerdere selecteren',exact:true}).click();
    const first=page.getByRole('checkbox',{name:/DEMO-1/});
    await first.focus(); await page.keyboard.press('Space');
    assert(await first.isChecked(),'Keyboard selection failed');
    const snapshot=await page.locator(view==='list'?'.list-table':'.board').ariaSnapshot();
    assert(snapshot.includes('[checked]'),'Checked state missing from accessibility tree');
    if(view==='list')assert(snapshot.includes('row'),'Selected table lost row semantics');
    await page.keyboard.press('Space');
    assert(!await first.isChecked(),'Keyboard deselection failed');
    for(const theme of ['light','dark']) {
      await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      const colors=await page.locator('.ref').first().evaluate(el=>{
        const style=getComputedStyle(el);
        const surface=document.createElement('div');surface.style.background='var(--surface-3)';document.body.append(surface);
        const bg=getComputedStyle(surface).backgroundColor;surface.remove();return {fg:style.color,bg};
      });
      const luminance=color=>{
        const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
        return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
      };
      const a=luminance(colors.fg),b=luminance(colors.bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      assert(ratio>=4.5,`Metadata contrast ${theme}: ${ratio}`);
    }
  }
}
