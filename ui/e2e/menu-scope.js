// The caller supplies an isolated, headless Playwright page.
export default async function menuScope(page, base = 'http://127.0.0.1:5186') {
  let actor = {handle: 'person', kind: 'human', credential_policy: {scopes: ['read', 'admin']}};
  const requests = [];
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    localStorage.setItem('hegemone_locale', new URLSearchParams(location.search).get('language') || 'en');
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    requests.push(path);
    let data = [];
    if (path === '/session') data = {csrf_token: 'synthetic'};
    else if (path === '/setup') data = {setup_required: false};
    else if (path === '/me') data = actor;
    else if (path === '/onboarding') data = {required: false};
    else if (path === '/projects') data = [{key: 'DEMO', name: 'Demo project'}];
    else if (path.endsWith('/states')) data = [{name: 'todo', closed: false}];
    else if (path.endsWith('/state-counts')) data = {todo: 0};
    else if (path.endsWith('/triage-chat')) data = {messages: [], pending: null};
    else if (path.startsWith('/events')) return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': synthetic\n\n'});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  for (const language of ['en', 'nl']) {
    await page.goto(`${base}/DEMO?language=${language}`);
    const trigger = page.locator('.tb-more');
    await trigger.click();
    const menu = page.getByRole('menu');
    const project = menu.getByRole('group', {name: 'Project', exact: true});
    const site = menu.getByRole('group', {name: 'Site', exact: true});
    if (await project.getByRole('menuitem').count() !== 3 || await site.getByRole('menuitem').count() !== 4) {
      throw new Error(`Incorrect project/site menu grouping (${language})`);
    }
    await page.keyboard.press('Escape');
    await menu.waitFor({state: 'hidden'});
    if (!await trigger.evaluate(el => el === document.activeElement)) throw new Error('Menu dismissal lost trigger focus');
    await trigger.click();
    await project.getByRole('menuitem', {name: language === 'en' ? 'Chat with triage' : 'Chat met triage'}).click();
    await page.getByRole('dialog').waitFor();
    if (!requests.some(path => path.includes('/projects/DEMO/triage-chat'))) throw new Error('Project chat did not keep project scope');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    await trigger.click();
    await site.getByRole('menuitem', {name: language === 'en' ? 'Webhook deliveries' : 'Webhook-leveringen'}).click();
    await page.getByRole('dialog').waitFor();
    if (!requests.includes('/webhook-deliveries')) throw new Error('Deliveries did not use site scope');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
  }
  for (const kind of ['human', 'agent']) {
    actor = {handle: 'person', kind, credential_policy: {scopes: ['read']}};
    await page.goto(`${base}/DEMO?language=en`);
    await page.locator('.tb-more').click();
    const menu = page.getByRole('menu');
    if (await menu.getByRole('menuitem', {name: 'Installation settings'}).count()) throw new Error('Installation permission gate was lost');
    const humanOnly = menu.getByRole('menuitem', {name: /Agents & users|Chat with triage|Webhook deliveries/});
    if (await humanOnly.count() !== (kind === 'human' ? 3 : 0)) throw new Error('Human-only menu gate was lost');
  }
}
