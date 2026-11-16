// Synthetic relation readability and interaction regression.
export default async function relatedList(page, base = 'http://127.0.0.1:5189') {
  const types = ['blocks', 'blocked_by', 'duplicate_of', 'duplicated_by', 'relates_to'];
  const title = 'A complete related ticket title with a longunbrokenword'.repeat(4);
  let opened = false;
  let removed = false;
  const item = {ref:'DEMO-1', project:'DEMO', title:'Example task', state:'todo', labels:[], comments:[],
    children:[], children_detail:[], relations:{}, relations_detail:Object.fromEntries(types.map((type, index) =>
      [type, [{ref:`OTHER-${index + 1}`, title, state:index === 0 ? 'Released' : 'todo', state_group:index === 0 ? 'completed' : 'unstarted'}]]))};
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    const language = new URLSearchParams(location.search).get('language');
    if (language) localStorage.setItem('hegemone_locale', language);
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    let data = [];
    if (path === '/session') data = {csrf_token:'synthetic'};
    else if (path === '/setup') data = {setup_required:false};
    else if (path === '/onboarding') data = {required:false};
    else if (path === '/me') data = {handle:'person', kind:'human'};
    else if (path === '/projects') data = [{key:'DEMO', name:'Demo project'}];
    else if (path.endsWith('/states')) data = [{name:'todo', group:'unstarted'}];
    else if (path.endsWith('/state-counts')) data = {todo:1};
    else if (path === '/projects/DEMO/items') data = [item];
    else if (path === '/items/DEMO-1') data = item;
    else if (path === '/items/OTHER-1') { opened = true; data = {...item, ref:'OTHER-1', title:'Opened related task', relations_detail:{}}; }
    else if (route.request().method() === 'DELETE' && path.endsWith('/relations')) { removed = true; return route.fulfill({status:204}); }
    else if (path.endsWith('/subscribers')) data = {subscribers:[]};
    else if (path.startsWith('/events')) return route.fulfill({status:200, contentType:'text/event-stream', body:': synthetic\n\n'});
    return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(data)});
  });
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  for (const language of ['en', 'nl']) {
    for (const width of [375, 1280]) {
      await page.setViewportSize({width,height:1000});
      await page.goto(`${base}/DEMO/1?language=${language}`);
      await page.locator('.rel-list').first().waitFor({state:'attached'});
      // Mobile properties start collapsed.
      if (!await page.locator('.rel-list').first().isVisible()) {
        await page.locator('.rail-props-toggle').click();
      }
      const colors = await page.locator('.rel-head').evaluateAll(els => els.map(el => getComputedStyle(el).color));
      assert(new Set(colors).size === 5, 'Relation types lack distinct colors');
      assert(await page.locator('.rel-title').first().innerText() === title, 'Title content lost');
      for (const row of await page.locator('.rel-title').all()) {
        assert(await row.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1), 'Title clipped');
      }
      assert(await page.locator('.rel-item.completed').count() === 1, 'Cross-project completion missing');
      assert(await page.locator('.rel-item.completed .rel-title').evaluate(el => getComputedStyle(el).textDecorationLine.includes('line-through')), 'Completed title is not struck through');
      assert(await page.locator('.drawer-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Drawer overflows');
    }
  }
  await page.locator('.rel-link').first().click();
  await page.getByText('Opened related task', {exact:true}).waitFor();
  assert(opened, 'Related ticket did not open');
  await page.goto(`${base}/DEMO/1?language=en`);
  const row = page.locator('.rel-item').first();
  await row.hover();
  await row.locator('.rel-unlink').click();
  assert(!removed, 'Unlink bypassed confirmation');
  await page.locator('.confirm-bar button').first().click();
  await page.waitForTimeout(100);
  assert(removed, 'Confirmed unlink failed');
}
