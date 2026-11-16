// Synthetic API responses exercise reading and explicit editing without live data.
export default async function drawerDetails(page, base = 'http://127.0.0.1:5197') {
  let item;
  const writes = [];
  const description = 'Selectable description with a [reference link](https://example.com/guide). ' + 'Long readable content. '.repeat(35);
  await page.addInitScript(() => {
    localStorage.setItem('betonning_session', '1');
    localStorage.setItem('hegemone_locale', new URLSearchParams(location.search).get('language') || 'en');
    sessionStorage.removeItem('betonning-md-preview');
  });
  await page.route('https://example.com/**', route => route.fulfill({contentType:'text/html',body:'Synthetic reference'}));
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    let data = [];
    if (path === '/session') data = {csrf_token:'synthetic'};
    else if (path === '/setup') data = {setup_required:false};
    else if (path === '/me') data = {id:1,handle:'person',kind:'human'};
    else if (path === '/users') data = [{id:1,handle:'person',kind:'human',active:true}];
    else if (path === '/projects') data = [{key:'DEMO',name:'Demo project',triage_enabled:false}];
    else if (path === '/onboarding') data = {required:false};
    else if (path.endsWith('/states')) data = [{name:'todo',group:'unstarted',color:'#157f70'},{name:'doing',group:'started',color:'#9465b0'}];
    else if (path.endsWith('/state-counts')) data = {todo:1,doing:0};
    else if (path === '/projects/DEMO/labels') data = ['feature','complex'].map(name => ({name}));
    else if (path === '/projects/DEMO/items') data = [item];
    else if (path === '/items/DEMO-1') {
      if (request.method() === 'PATCH') { const body = request.postDataJSON(); writes.push(body); item = {...item,...body}; }
      data = item;
    } else if (path.endsWith('/subscribers')) data = {subscribers:[]};
    else if (path.startsWith('/events')) return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
    await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  for (const language of ['en', 'nl']) {
    item = {id:1,ref:'DEMO-1',project:'DEMO',title:'Clear details',description_md:description,state:'todo',workload:'heavy',labels:['feature','complex'],comments:[],relations:{},children:[],created_at:'2026-09-01T12:00:00Z',updated_at:'2026-09-02T12:00:00Z'};
    writes.length = 0;
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(`${base}/DEMO/1?language=${language}`);
    const drawer = page.locator('.dw');
    const desc = drawer.locator('.desc.md');
    await desc.waitFor();
    if (await drawer.locator('.section-meta').count() !== 1 || await drawer.locator('.dw-rail [title*="2026"]').count()) throw new Error('Dates must appear once at the top');
    await page.setViewportSize({width:390,height:844});
    if (await desc.evaluate(el => el.scrollWidth > el.clientWidth)) throw new Error('Long description overflows');
    if (await drawer.locator('.section-actions').first().evaluate(el => el.scrollWidth > el.clientWidth)) throw new Error('Description actions overflow');
    await page.setViewportSize({width:1440,height:1000});
    await desc.click({position:{x:20,y:20}});
    if (await drawer.locator('.desc-editor').count()) throw new Error('Reading must not enter edit mode');
    const selected = await desc.evaluate(el => {
      const range = document.createRange(); range.selectNodeContents(el);
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
      return selection.toString();
    });
    if (!selected.startsWith('Selectable description')) throw new Error('Text selection failed');
    const popupPromise = page.waitForEvent('popup');
    await desc.getByRole('link',{name:'reference link'}).click();
    const popup = await popupPromise; await popup.waitForLoadState(); await popup.close();
    if (await drawer.locator('.desc-editor').count()) throw new Error('Link entered edit mode');
    await drawer.locator('.work-class').getByText('complex',{exact:true}).waitFor();
    await drawer.getByText(language === 'en' ? 'Estimated amount of work.' : 'Geschatte hoeveelheid werk.',{exact:true}).waitFor();
    const edit = drawer.getByRole('button',{name:language === 'en' ? 'Edit description' : 'Omschrijving bewerken',exact:true});
    await edit.focus(); await page.keyboard.press('Enter');
    const editor = drawer.locator('.desc-editor');
    await editor.locator('textarea').fill('Draft stays open');
    await drawer.locator('.dw-title').click();
    if (!(await editor.isVisible()) || writes.length) throw new Error('Blur closed or saved description');
    await editor.getByRole('button',{name:language === 'en' ? 'Cancel' : 'Annuleren',exact:true}).click();
    if (!(await desc.textContent()).includes('Selectable description') || writes.length) throw new Error('Cancel failed');
    await edit.click(); await editor.locator('textarea').fill('Saved description');
    await editor.getByRole('button',{name:language === 'en' ? 'Save' : 'Opslaan',exact:true}).click();
    await desc.getByText('Saved description',{exact:true}).waitFor();
    if (writes.at(-1)?.description_md !== 'Saved description') throw new Error('Explicit save failed');
    const status = drawer.getByRole('radiogroup',{name:language === 'en' ? 'Status' : 'Status',exact:true});
    await status.getByRole('radio',{name:'doing',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('.dw-rail [role="radio"][aria-checked="true"]')?.textContent.trim() === 'doing');
    if (writes.at(-1)?.state !== 'doing') throw new Error('Status quick control failed');
    const selectedStatus = status.getByRole('radio',{name:'doing',exact:true});
    if (!(await selectedStatus.getAttribute('class')).includes('colored') || !(await selectedStatus.getAttribute('style')).includes('#9465b0')) throw new Error('Status lost selected color');
    const effort = drawer.getByRole('radiogroup',{name:language === 'en' ? 'Effort' : 'Omvang',exact:true});
    await effort.getByRole('radio',{name:language === 'en' ? 'Light' : 'Licht',exact:true}).click();
    if (writes.at(-1)?.workload !== 'light') throw new Error('Effort quick control failed');

  }
}
