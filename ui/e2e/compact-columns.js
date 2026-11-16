// Synthetic coverage for compact columns and unchanged workflow order.
export default async function compactColumns(page, base = 'http://127.0.0.1:5192') {
  const states = [
    {name:'backlog', closed:false}, {name:'todo', closed:false},
    {name:'in-progress', closed:false}, {name:'done', closed:true},
    {name:'cancelled', closed:true},
  ];
  const items = Array.from({length:24}, (_, i) => ({ref:`DEMO-${i+1}`, project:'DEMO',
    title:`Example task ${i+1}`, state:'todo', labels:[], comments:[], children:[], relations:{}}));
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session','1');
    localStorage.setItem('hegemone_locale',new URLSearchParams(location.search).get('language') || 'en');
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1','');
    let data = [];
    if(path === '/session') data = {csrf_token:'synthetic'};
    else if(path === '/setup') data = {setup_required:false};
    else if(path === '/me') data = {handle:'person',kind:'human',role:'admin'};
    else if(path === '/onboarding') data = {required:false};
    else if(path === '/projects') data = [{key:'DEMO',name:'Demo'}];
    else if(path.endsWith('/states')) data = states;
    else if(path.endsWith('/state-counts')) data = {todo:24};
    else if(path === '/projects/DEMO/items') data = items;
    else if(path.startsWith('/items/DEMO-')) data = items.find(x=>path.endsWith(x.ref)) || items[0];
    else if(path.endsWith('/subscribers')) data = {subscribers:[]};
    else if(path.startsWith('/events')) return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert = (value,message) => {if(!value)throw new Error(message);};
  for(const language of ['en','nl']) {
    for(const width of [1920,1280,375]) {
      await page.setViewportSize({width,height:800});
      await page.goto(`${base}/DEMO?language=${language}`);
      await page.locator('.card').first().waitFor();
      const todo = page.locator('.column[data-col="todo"]');
      const done = page.locator('.column[data-col="done"]');
      const openWidth = (await todo.boundingBox()).width;
      const collapsedWidth = (await done.boundingBox()).width;
      if(width > 1000) assert(collapsedWidth < openWidth - 20,'Collapsed column did not free horizontal space');
      assert(await page.locator('.column').evaluateAll(els=>els.map(el=>el.dataset.col).join(',')) === states.map(x=>x.name).join(','),'Workflow order changed');
      assert(await page.locator('.column[data-col="backlog"] .col-add').count() === 1,'Empty column lost its drop/create target');
      await done.locator('.col-collapse').click();
      assert(!await done.evaluate(el=>el.classList.contains('collapsed')),'Column did not expand');
      await done.locator('.col-collapse').click();
      await todo.locator('.col-collapse').click();
      assert(await todo.evaluate(el=>el.classList.contains('collapsed')),'Open state cannot collapse');
      await todo.locator('.col-collapse').click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),'Horizontal overflow');
      if(width > 1000) {
        await todo.evaluate(el=>{el.scrollTop=150;});
        await todo.locator('.card').nth(3).click();
        const previous = await todo.evaluate(el=>el.scrollTop);
        await page.locator('.drawer-dialog').waitFor();
        await page.keyboard.press('Escape');
        await page.locator('.drawer-dialog').waitFor({state:'detached'});
        assert(Math.abs(await todo.evaluate(el=>el.scrollTop)-previous)<2,'Drawer reset column scroll');
      }
    }
  }
}
