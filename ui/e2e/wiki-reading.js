// The caller supplies an isolated, headless Playwright page.
export default async function wikiReading(page, base = 'http://127.0.0.1:5192') {
  let actor = {handle: 'person', kind: 'human'};
  const longTitle = 'A readable guide with a deliberately long title for browsing project knowledge without losing the meaning';
  let pages = [
    {slug: 'matching', title: 'Reading guide', body_md: '# Reading guide\n\nUseful instructions.', protected: true},
    {slug: 'different', title: 'Page title', body_md: '# Different introduction\n\nMore instructions.', protected: false},
    {slug: 'long-title', title: longTitle, body_md: `# ${longTitle}\n\nLong title content.`, protected: false},
  ];
  const writes = [];
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    localStorage.setItem('hegemone_locale', new URLSearchParams(location.search).get('language') || 'en');
  });
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    let data = [];
    if (path === '/session') data = {csrf_token: 'synthetic'};
    else if (path === '/setup') data = {setup_required: false};
    else if (path === '/me') data = actor;
    else if (path === '/onboarding') data = {required: false};
    else if (path === '/projects') data = [{key: 'DEMO', name: 'Demo project'}];
    else if (path.endsWith('/states')) data = [{name: 'todo', closed: false}];
    else if (path.endsWith('/state-counts')) data = {todo: 0};
    else if (path === '/projects/DEMO/wiki') data = pages;
    else if (path === '/wiki/index') data = pages.map(p => ({scope: 'DEMO', slug: p.slug}));
    else if (path === '/wiki-protection') {
      const body = request.postDataJSON();
      writes.push(body);
      pages = pages.map(p => p.slug === body.slug ? {...p, protected: body.protected} : p);
      data = {};
    } else if (path.startsWith('/events')) return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': fixture\n\n'});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  for (const language of ['en', 'nl']) {
    for (const kind of ['human', 'agent']) {
      actor = {...actor, kind};
      pages = pages.map(p => ({...p, protected: p.slug === 'matching'}));
      await page.setViewportSize({width: 1440, height: 1000});
      await page.goto(`${base}/DEMO?view=wiki&language=${language}`);
      await page.locator('.wiki-row').filter({hasText: 'Reading guide'}).click();
      const article = page.locator('article.wiki-doc');
      if (await article.locator('h1').count() !== 1) throw new Error('Matching heading was repeated');
      await article.getByText(language === 'en' ? 'Protected knowledge' : 'Beschermde kennis', {exact: true}).waitFor();
      await article.getByRole('button', {name: language === 'en' ? 'Page actions' : 'Pagina-acties', exact:true}).click();
      const protect=article.getByRole('button', {name:language === 'en' ? 'Remove protection' : 'Bescherming opheffen',exact:true});
      if (await protect.count() !== (kind === 'human' ? 1 : 0)) throw new Error('Protection action permission changed');
      if (kind === 'human') {
        await protect.click();
        await page.waitForFunction(()=>!document.querySelector('.wiki-protected'));
        const write = writes.at(-1);
        if (write.project !== 'DEMO' || write.slug !== 'matching' || write.protected !== false) throw new Error('Protection scope or payload changed');
      } else await article.getByRole('button', {name: language === 'en' ? 'Page actions' : 'Pagina-acties', exact:true}).click();
      await page.locator('.wiki-row').filter({hasText: 'Page title'}).click();
      if (await article.locator('h1').count() !== 2) throw new Error('Different heading was omitted');
      await page.locator('.wiki-row').filter({hasText: longTitle}).click();
      const geometry = await article.evaluate(el => ({width: el.getBoundingClientRect().width, overflow: el.scrollWidth > el.clientWidth}));
      if (geometry.width > 850 || geometry.overflow) throw new Error('Reading width or long title overflow');
      await article.getByRole('button', {name: language === 'en' ? 'Edit' : 'Bewerken', exact: true}).click();
      const body = await article.locator('textarea').inputValue();
      if (body !== `# ${longTitle}\n\nLong title content.`) throw new Error('Stored Markdown changed');
      await article.getByRole('button', {name: language === 'en' ? 'Cancel' : 'Annuleren', exact: true}).click();
      await page.setViewportSize({width: 390, height: 844});
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Narrow article overflow');
      await page.locator('.wiki-mobile-bar').getByRole('button', {name: language === 'en' ? 'Pages' : "Pagina's", exact: true}).click();
      if (await page.locator('.wiki-nav').evaluate(el => el.scrollWidth > el.clientWidth)) throw new Error('Narrow navigation overflow');
    }
  }
}
