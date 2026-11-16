// Synthetic regression for explicit editor saving and narrow drawer content.
export default async function editLayoutSettings(page, base = 'http://127.0.0.1:5189') {
  const longURL = 'https://example.org/' + 'long-path-segment'.repeat(30);
  const original = {ref:'DEMO-1', project:'DEMO', title:'Example task', state:'todo',
    description_md:longURL, has_plan:true, labels:[], comments:[], relations:{}, children:[], children_detail:[]};
  let item = {...original};
  let writes = 0;
  const project = {key:'DEMO', name:'Demo project', auto_lock_enabled:true};
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
    else if (path === '/me') data = {handle:'person', kind:'human', role:'admin'};
    else if (path === '/projects') data = [project];
    else if (path === '/projects/DEMO/auto-lock') {
      project.auto_lock_enabled = route.request().postDataJSON().enabled;
      data = project;
    }
    else if (path.endsWith('/states')) data = [{name:'todo', closed:false}];
    else if (path.endsWith('/state-counts')) data = {todo:1};
    else if (path.endsWith('/ref-candidates') || path === '/search') data = [{ref:'DEMO-2', title:'A very long result title '.repeat(15)}];
    else if (path === '/projects/DEMO/items') data = [item];
    else if (path === '/items/DEMO-1') {
      if (route.request().method() === 'PATCH') { writes++; Object.assign(item, route.request().postDataJSON()); }
      data = item;
    }
    else if (path.endsWith('/plan')) data = {plan_md:'Example plan'};
    else if (path.endsWith('/subscribers')) data = {subscribers:[]};
    else if (path.endsWith('/access')) data = {type_defaults:{}, agents:[]};
    else if (path.startsWith('/events')) return route.fulfill({status:200, contentType:'text/event-stream', body:': synthetic\n\n'});
    return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(data)});
  });
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  for (const language of ['en', 'nl']) {
    item = {...original}; writes = 0;
    project.auto_lock_enabled = true;
    await page.setViewportSize({width:1280, height:900});
    await page.goto(`${base}/DEMO/1?language=${language}`);
    const title = page.locator('.dw-title');
    await title.waitFor();
    await title.click();
    await page.locator('.title-edit').fill('Draft title');
    await page.locator('.drawer-dialog').click({position:{x:10,y:10}});
    assert(await page.locator('.title-edit').count() === 1 && writes === 0, 'Title blur saved or closed');
    await page.locator('.dw-title-area .primary').click();
    await title.waitFor();
    assert(await title.innerText() === 'Draft title' && writes === 1, 'Explicit title save failed');
    await page.getByRole('button',{name:language === 'en' ? 'Edit description' : 'Omschrijving bewerken',exact:true}).click();
    await page.locator('.desc-editor textarea').fill('Draft description');
    await title.click();
    assert(await page.locator('.desc-editor textarea').inputValue() === 'Draft description' && writes === 1, 'Description blur saved or closed');
    await page.locator('.desc-editor .primary').click();
    await page.locator('.desc.md').waitFor();
    assert(writes === 2, 'Explicit description save failed');
    await page.locator('.title-edit').press('Escape');
    const show = page.getByRole('button', {name:language === 'en' ? 'Show' : 'Toon', exact:true});
    await show.click();
    await page.locator('.plan-body.editable').click();
    await page.locator('.plan-editor textarea').fill('Draft plan');
    await title.click();
    assert(await page.locator('.plan-editor textarea').inputValue() === 'Draft plan' && writes === 2, 'Plan blur saved or closed');
    await page.locator('.plan-editor .primary').click();
    await page.locator('.plan-body.editable').waitFor();
    assert(writes === 3, 'Explicit plan save failed');
    await page.locator('.title-edit').press('Escape');
    // Reload the original long URL fixture for mobile and dropdown checks.
    item = {...original};
    await page.reload();
    await page.locator('.desc').waitFor();
    for (const width of [375, 1280]) {
      await page.setViewportSize({width,height:900});
      assert(await page.locator('.desc').evaluate(el => el.scrollWidth <= el.clientWidth + 1), `Description overflow at ${width}`);
      assert(await page.locator('.drawer-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1), `Drawer overflow at ${width}`);
    }
    await page.getByRole('button', {name:language === 'en' ? 'Add relation' : 'Relatie leggen', exact:true}).click();
    await page.locator('.rel-target').fill('2');
    const result = page.locator('#rel-suggest [role="option"]');
    await result.waitFor();
    assert(await result.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Relation result overflows');
    assert(await result.locator('.muted').evaluate(el => getComputedStyle(el).whiteSpace !== 'nowrap'), 'Relation title is clipped');
    await result.click();
    assert(await page.locator('.rel-target').inputValue() === 'DEMO-2', 'Relation result selection failed');
    await page.goto(`${base}/DEMO?language=${language}`);
    await page.getByRole('button', {name:language === 'en' ? 'More actions' : 'Meer acties', exact:true}).click();
    await page.getByRole('menuitem', {name:language === 'en' ? 'Project settings' : 'Projectinstellingen', exact:true}).click();
    const toggle = page.getByRole('switch', {name:language === 'en' ? 'Automatic ticket lock' : 'Automatisch ticketslot', exact:true});
    assert(await toggle.getAttribute('aria-checked') === 'true', 'Lock setting default missing');
    await toggle.click();
    await page.waitForFunction(() => document.querySelector('[role="switch"][aria-label="Automatic ticket lock"], [role="switch"][aria-label="Automatisch ticketslot"]')?.getAttribute('aria-checked') === 'false');
    assert(project.auto_lock_enabled === false, 'Lock setting did not reach API');
  }
}
