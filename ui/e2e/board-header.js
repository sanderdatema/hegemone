// Synthetic scrolling regression; the caller supplies an isolated Playwright page.
export default async function boardHeader(page, base = 'http://127.0.0.1:5186') {
  const items = Array.from({length: 40}, (_, i) => ({
    ref: `DEMO-${i + 1}`, project: 'DEMO', title: `Example task ${i + 1}`,
    state: 'todo', labels: [],
  }));
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
    else if (path.endsWith('/items')) data = items;
    else if (path.startsWith('/events')) return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': synthetic\n\n'});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.setViewportSize({width: 1280, height: 720});
  for (const language of ['en', 'nl']) {
    await page.goto(`${base}/DEMO?view=board&language=${language}`);
    await page.locator('.card').first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    const column = page.locator('.column[data-col="todo"]');
    for (const scrollTop of [80, 240, 600]) {
      await column.evaluate((el, y) => { el.scrollTop = y; }, scrollTop);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      const geometry = await column.evaluate(el => {
        const head = el.querySelector('.col-head');
        const c = el.getBoundingClientRect(), h = head.getBoundingClientRect();
        const hit = document.elementFromPoint(h.x + h.width / 2, c.y + 2);
        return {topGap: h.top - c.top, height: h.height, covered: head.contains(hit), scrollTop: el.scrollTop};
      });
      if (geometry.scrollTop === 0 || Math.abs(geometry.topGap) > 1 || !geometry.covered || geometry.height < 30) {
        throw new Error(`Header coverage failed (${language}, ${scrollTop}): ${JSON.stringify(geometry)}`);
      }
    }
  }
}
