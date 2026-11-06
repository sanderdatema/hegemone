// Lokale browserregressie met uitsluitend synthetische API-fixtures.
export default async function languageNavigation(page, base='http://127.0.0.1:8141') {
  await page.route('**/TEAM', async route => route.fulfill({response: await route.fetch({url: base + '/'})}));
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    const request = route.request(); let data = [];
    if (path === '/setup') data = {required: false, enabled: false};
    else if (path === '/session') data = {csrf_token: 'fixture', user: {id: 1, handle: 'operator', kind: 'human'}};
    else if (path === '/me') data = {id: 1, handle: 'operator', display_name: 'Operator', kind: 'human'};
    else if (path === '/onboarding') data = {required: false, locale: 'en', step: 'complete'};
    else if (path === '/projects') data = [{key: 'TEAM', name: 'Team'}];
    else if (path === '/users') data = [{id: 1, handle: 'operator', display_name: 'Operator', kind: 'human', active: true}];
    else if (path.endsWith('/states')) data = [{name: 'todo', group: 'unstarted'}];
    else if (path.endsWith('/state-counts')) data = {todo: 0};
    else if (path === '/inbox') data = {items: [], unread: 0};
    else if (path.endsWith('/labels')) data = [{name: 'bug'}, {name: 'routine'}];
    else if (path.endsWith('/milestones')) data = [];
    else if (path.endsWith('/items')) data = request.method() === 'POST' ? {ref: 'TEAM-1', title: 'Test ticket'} : [];
    else if (path.endsWith('/items/TEAM-1')) data = {ref: 'TEAM-1', title: 'Test ticket', state: 'todo', labels: []};
    if (path === '/events/stream') return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': heartbeat\n\n'});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.goto(base);
  await page.getByRole('button', {name: 'Sign in', exact: true}).waitFor();
  await page.getByRole('button', {name: 'Nederlands', exact: true}).click();
  await page.getByRole('button', {name: 'Inloggen', exact: true}).waitFor();
  await page.reload();
  await page.getByRole('button', {name: 'Inloggen', exact: true}).waitFor();
  await page.getByLabel('API-key', {exact: true}).fill('synthetic-login-fixture');
  await page.getByRole('button', {name: 'Inloggen', exact: true}).click();
  await page.getByRole('button', {name: 'Bord', exact: true}).waitFor();
  await page.getByRole('button', {name: 'Account (@operator)', exact: true}).click();
  await page.getByRole('menuitem', {name: 'English', exact: true}).click();
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name: 'Board', exact: true}).waitFor();
  await page.getByRole('button', {name: 'New ticket', exact: true}).waitFor();
  await page.getByRole('button', {name: 'New ticket', exact: true}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByLabel('Title', {exact: true}).fill('English ticket');
  await page.getByRole('textbox').nth(1).fill('Description');
  await page.getByRole('button', {name: 'Create ticket', exact: true}).click();
  if (await page.locator('html').getAttribute('lang') !== 'en') throw new Error('Documenttaal niet bijgewerkt');
  await page.reload();
  await page.getByRole('button', {name: 'Board', exact: true}).waitFor();
  if (!(await page.title()).includes('Hegemone')) throw new Error('Productnaam niet bijgewerkt');
  await page.screenshot({path: '/tmp/hegemone-english-navigation.png'});
}
