// Long navigation, long document titles and both color schemes.
export default async function wikiLayout(page,base='http://127.0.0.1:5201') {
  const title='A complete and readable knowledge document with a long title that must remain legible on a small screen';
  const current={slug:'guide',title,body_md:`# ${title}\n\nA useful introduction. See [[page-0]].\n\n## Reading\n\n${'A paragraph of useful information. '.repeat(10)}\n\n## Example\n\n\`\`\`\n${'longcode'.repeat(80)}\n\`\`\``,revision:'revision'};
  const pages=[current,...Array.from({length:100},(_,i)=>({slug:`page-${i}`,title:`Knowledge page ${i} with a longer descriptive title`,body_md:'See [[guide]].',revision:'other'}))];
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');localStorage.setItem('hegemone_locale','en');});
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:'human',role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Atlas'}];
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path==='/projects/DEMO/wiki')data=pages;
    else if(path==='/wiki/index')data=pages.map(p=>({slug:p.slug,title:p.title,scope:'DEMO'}));
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(ok,message)=>{if(!ok)throw new Error(message);};
  await page.goto(`${base}/DEMO?view=wiki&wikiPage=guide&wikiScope=project`);
  await page.locator('.wiki-doc-title').waitFor();
  for(const width of [1440,390])for(const theme of ['light','dark']) {
    await page.setViewportSize({width,height:950});
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    if(width===390 && await page.locator('.wiki-mobile-bar button').first().getAttribute('aria-expanded')==='false')await page.locator('.wiki-mobile-bar button').first().click();
    assert(await page.locator('.wiki-view').evaluate(el=>el.scrollWidth<=el.clientWidth),'Horizontal overflow');
    assert(await page.locator('.wiki-list').evaluate(el=>el.scrollHeight>el.clientHeight),'Long page list not independently scrollable');
    assert(await page.locator('.wiki-search input').evaluate(el=>getComputedStyle(el).borderTopWidth==='0px'),'Double search border');
    assert(await page.locator('.wiki-doc-title').evaluate(el=>el.scrollWidth<=el.clientWidth),'Long title clipped');
    assert(await page.locator('.wiki-row').evaluateAll(rows=>rows.every(row=>{
      const r=row.getBoundingClientRect(),t=row.querySelector('.wiki-row-title').getBoundingClientRect();
      return t.top>=r.top && t.bottom<=r.bottom;
    })),'Wrapped title extends beyond its row');
    assert(await page.locator('.wiki-article [data-wiki]').evaluate(el=>getComputedStyle(el).cursor==='pointer'),'Wiki link lacks hand cursor');
    await page.screenshot({path:`/tmp/wiki-layout-${width}-${theme}.png`,animations:'disabled'});
  }
}
