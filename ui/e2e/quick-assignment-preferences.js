// The caller supplies an isolated, headless Playwright page.
export default async function quickAssignmentPreferences(page, base = 'http://127.0.0.1:5186') {
  const actor = {handle: 'person', kind: 'human', display_name: 'Person'};
  const roster = [actor,
    {handle: 'builder', kind: 'agent', agent_type: 'coding', active: true},
    {handle: 'receiver', kind: 'agent', agent_type: 'hermes', active: true},
    {handle: 'sleeping', kind: 'agent', agent_type: 'coding', active: false}];
  const item = {ref: 'DEMO-1', id: 1, project: 'DEMO', title: 'Synthetic task', description_md: '', state: 'todo',
    assignee: null, labels: [], comments: [], relations: {}, children: [], children_detail: [], updated_at: '2026-01-01T12:00:00Z'};
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    localStorage.setItem('hegemone_locale', new URLSearchParams(location.search).get('language') || 'en');
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    let data = [];
    if (path === '/session') data = {csrf_token: 'synthetic'};
    else if (path === '/setup') data = {setup_required: false};
    else if (path === '/me') data = actor;
    else if (path === '/users') data = roster;
    else if (path === '/users/me/settings') data = {subscribe_all: false};
    else if (path === '/settings/model-classes') data = {classes: [], mapping: {}};
    else if (path === '/onboarding') data = {required: false};
    else if (path === '/projects') data = [{key: 'DEMO', name: 'Demo project', triage_enabled: false}];
    else if (path.endsWith('/states')) data = [{name: 'todo', group: 'unstarted', is_default: true}];
    else if (path.endsWith('/state-counts')) data = {todo: 1};
    else if (path === '/projects/DEMO/items') data = [item];
    else if (path === '/items/DEMO-1') data = item;
    else if (path.endsWith('/subscribers')) data = {subscribers: []};
    else if (path === '/inbox') data = {items: []};
    else if (path.startsWith('/events')) return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': synthetic\n\n'});
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  for (const language of ['en', 'nl']) {
    await page.goto(`${base}/DEMO?language=${language}`);
    await page.evaluate(() => localStorage.removeItem('hegemone_quick_assignment:person'));
    await page.reload();
    const openSettings = async () => {
      await page.getByRole('button', {name: 'Account (@person)', exact: true}).click();
      await page.getByRole('menuitem', {name: language === 'en' ? 'My settings' : 'Mijn instellingen', exact: true}).click();
      return page.getByRole('region', {name: language === 'en' ? 'Quick assignment buttons' : 'Knoppen voor snel toewijzen'});
    };
    const section = await openSettings();
    const builder = section.getByRole('checkbox', {name: /@builder/});
    const receiver = section.getByRole('checkbox', {name: /@receiver/});
    await builder.waitFor();
    if (!await builder.isChecked() || await receiver.isChecked()) throw new Error('Defaults changed');
    if (await section.getByRole('checkbox', {name: /@sleeping/}).count()) throw new Error('Inactive agent offered');
    await builder.uncheck();
    await receiver.check();
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    await page.locator('.tb-new').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', {name: '→ receiver', exact: true}).waitFor();
    if (await dialog.getByRole('button', {name: '→ builder', exact: true}).count()) throw new Error('New ticket ignored preference');
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});
    await page.goto(`${base}/DEMO/1?language=${language}`);
    await page.getByRole('button', {name: '→ receiver', exact: true}).waitFor();
    if (await page.getByRole('button', {name: '→ builder', exact: true}).count()) throw new Error('Detail/reload ignored preference');
    await page.goto(`${base}/DEMO?language=${language}`);
    const empty = await openSettings();
    await empty.getByRole('checkbox', {name: /@receiver/}).uncheck();
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    await page.locator('.tb-new').click();
    await page.getByRole('dialog').waitFor();
    if (await page.locator('.quick-assign').count()) throw new Error('Empty preference still shows shortcuts');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    const reset = await openSettings();
    await reset.getByRole('button', {name: language === 'en' ? 'Use defaults' : 'Standaard gebruiken', exact: true}).click();
    if (!await reset.getByRole('checkbox', {name: /@builder/}).isChecked()) throw new Error('Reset failed');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state: 'hidden'});
  }
}
