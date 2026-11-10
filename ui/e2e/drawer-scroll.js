// Synthetic scrolling regression; the caller supplies an isolated Playwright page.
export default async function drawerScroll(page, base = 'http://127.0.0.1:5186') {
  const items = Array.from({length: 40}, (_, i) => ({
    ref: `DEMO-${i + 1}`, project: 'DEMO', title: `Example task ${i + 1}`,
    state: 'todo', labels: [],
  }));
  let answered = false;
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    localStorage.setItem('hegemone_locale', new URLSearchParams(location.search).get('language') || 'en');
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    let data = [];
    if (path === '/session') data = {csrf_token: 'synthetic'};
    else if (path === '/setup') data = {setup_required: false};
    else if (path === '/me') data = {handle: 'person', kind: 'human', role: 'admin'};
    else if (path === '/onboarding') data = {required: false};
    else if (path === '/projects') data = [{key: 'DEMO', name: 'Demo project'}];
    else if (path.endsWith('/states')) data = [{name: 'todo', closed: false}, {name: 'done', closed: true}];
    else if (path.endsWith('/state-counts')) data = {todo: items.length};
    else if (path.endsWith('/items')) data = answered ? [items[14], ...items.filter(it => it !== items[14])] : items;
    else if (path === '/comments/1/answer') { answered = true; data = {}; }
    else if (path === '/items/DEMO-15') data = {...items[14], description_md:'Example', comments:[{id:1, kind:'question', author:'person', body_md:'Choose an option', created_at:'2026-01-01T00:00:00Z', question_options:['Proceed'], answered_at: answered ? '2026-01-02T00:00:00Z' : null, answer_text: answered ? 'Proceed' : null}], relations:{}, children:[], children_detail:[]};
    else if (path.endsWith('/subscribers')) data = {subscribers:[]};
    else if (path.startsWith('/events')) return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': synthetic\n\n'});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.setViewportSize({width: 1280, height: 720});
  for (const language of ['en', 'nl']) {
    await page.goto(`${base}/DEMO?view=board&language=${language}`);
    await page.locator('.card').first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    const column = page.locator('.column[data-col="todo"]');
    const card = page.locator('.card[data-ref="DEMO-15"]');
    await card.click();
    if (await column.evaluate(el => el.scrollTop) < 100) throw new Error('Fixture did not scroll');
    await page.locator('.q-opt-btn').click();
    await page.locator('.confirm-bar button.primary').click();
    await page.locator('.q-tag').waitFor();
    await page.waitForFunction(() => document.querySelector('.column .card')?.getAttribute('data-ref') === 'DEMO-15');
    const before = await column.evaluate(el => el.scrollTop);
    await page.keyboard.press('Escape');
    await page.locator('.drawer-dialog').waitFor({state:'hidden'});
    await page.waitForTimeout(250);
    const after = await column.evaluate(el => el.scrollTop);
    if (Math.abs(before - after) > 2) throw new Error(`Column moved on close (${language}): ${before} -> ${after}`);
    if (!await card.evaluate(el => document.activeElement === el)) throw new Error('Focus was not restored');
    answered = false;
  }
}
