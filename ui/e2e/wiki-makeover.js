// Complete synthetic knowledge-base flow. No live content or credentials.
export default async function wikiMakeover(page,base='http://127.0.0.1:5201') {
  const body='# Getting started\n\nA readable introduction.\n\n## Overview\n\nFind the uniquephrase in this guide.\n\n## Overview\n\nDuplicate headings stay reachable.\n\n### Details\n\n[[glossary]] and [[glossary|Explicit alias]], plus [[global:shared]].\n\n```js\nconst safe = "<script>literal</script>";\n```';
  const primary={slug:'getting-started',title:'Getting started',body_md:body,updated_at:'2026-01-02T10:00:00Z',revision:'rev-1',protected:false};
  let pages=[], globalPages=[],writes=[],failLoad=false,conflict=false,protection=0,deletions=0,actorKind="human",archived=false;
  const reset=()=>{
    pages=[{...primary},{slug:'glossary',title:'Project glossary',body_md:'# Project glossary\n\nTerms explained.',updated_at:'2026-01-01T10:00:00Z',revision:'rev-g'},...Array.from({length:7},(_,i)=>({slug:`reference-${i}`,title:`Related guide ${i}`,body_md:'See [[getting-started]].',updated_at:'2025-01-01',revision:'ref'}))];
    globalPages=[{slug:'shared',title:'Shared agreements',body_md:'# Shared agreements\n\nGlobal text.',updated_at:'2026-01-01',revision:'shared'}];writes=[];conflict=false;
  };reset();
  await page.addInitScript(()=>{localStorage.setItem('betonning_session','1');const lang=new URLSearchParams(location.search).get('language');if(lang)localStorage.setItem('hegemone_locale',lang);sessionStorage.removeItem('betonning-md-preview');});
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={setup_required:false};
    else if(path==='/session')data={csrf_token:'synthetic'};
    else if(path==='/me')data={handle:'person',kind:actorKind,role:'admin'};
    else if(path==='/onboarding')data={required:false};
    else if(path==='/projects')data=[{key:'DEMO',name:'Atlas',archived_at:archived?'2026-01-01':null}];
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path==='/wiki/index')data=[...pages.map(p=>({scope:'DEMO',slug:p.slug,title:p.title})),...globalPages.map(p=>({scope:'global',slug:p.slug,title:p.title}))];
    else if(path==='/wiki' || path==='/projects/DEMO/wiki') {
      if(failLoad)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Fixture unavailable'})});
      if(req.method()==='POST'){const draft=req.postDataJSON();const created={...draft,slug:draft.slug.toLowerCase().replace(/ /g,'-'),revision:'new',updated_at:'2026-01-03'};pages.push(created);writes.push(draft);data=created;}
      else data=path==='/wiki'?globalPages:pages;
    }
    else if(path==='/wiki-protection'){protection++;const change=req.postDataJSON();pages=pages.map(p=>p.slug===change.slug?{...p,protected:change.protected}:p);data={};}
    else if(path.endsWith('/revisions/1'))data={revision:{id:1,title:'Getting started',body_md:body,author:'person',created_at:'2026-01-01'},previous:null};
    else if(path.endsWith('/revisions'))data=[{id:1,title:'Getting started',author:'person',created_at:'2026-01-01'}];
    else if(path.startsWith('/projects/DEMO/wiki/') || path.startsWith('/wiki/')) {
      const slug=decodeURIComponent(path.split('/').pop());const target=path.startsWith('/projects/')?pages:globalPages;const index=target.findIndex(p=>p.slug===slug);
      if(req.method()==='PATCH') {
        const draft=req.postDataJSON();
        if(conflict){conflict=false;target[index]={...target[index],body_md:'Concurrent saved content',revision:'concurrent'};return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Changed',error_code:'wiki_edit_conflict'})});}
        if(draft.expected_revision!==target[index].revision)throw new Error('Missing or wrong revision');
        if(actorKind==='agent' && target[index].protected)return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'pending',proposal_id:1})});
        writes.push(draft);target[index]={...target[index],...draft,revision:'updated',updated_at:'2026-01-03'};
      }
      if(req.method()==='DELETE'){deletions++;target.splice(index,1);return route.fulfill({status:204});}
      data=target[index]||{};
    }
    else if(path.startsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const assert=(x,m)=>{if(!x)throw new Error(m);};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const lang of ['en','nl']) {
    reset();actorKind='human';archived=false;await page.setViewportSize({width:1440,height:1000});
    await page.goto(`${base}/DEMO?view=wiki&language=${lang}`);
    await page.locator('.wiki-home h1').filter({hasText:'Atlas'}).waitFor();
    assert(await page.locator('.wiki-home h1').innerText()==='Atlas','Knowledge-base home missing');
    assert(await page.locator('.wiki-row').count()===9,'Page list incomplete');
    assert(await page.locator('.wiki-row-slug').count()===0,'Technical slugs still dominate navigation');
    await page.screenshot({path:`/tmp/wiki-makeover-home-${lang}.png`});
    await page.locator('.wiki-home-search input').fill('uniquephrase');
    await page.waitForFunction(()=>document.querySelectorAll('.wiki-row').length===1);
    assert((await page.locator('.wiki-row-snippet').innerText()).includes('uniquephrase'),'Body match context absent');
    await page.locator('.wiki-row').click();
    await page.locator('.wiki-doc-title').waitFor();
    await page.locator('.wiki-search .icon-btn').click();
    assert(await page.locator('.wiki-doc h1').count()===1,'Opening title duplicated');
    assert(await page.locator('.wiki-toc button').count()===3,'Outline incorrect');
    await page.locator('.wiki-toc button').nth(1).click();
    assert(await page.evaluate(()=>document.activeElement.id)==='wiki-section-overview-2','Outline anchor incorrect');
    assert(await page.locator('.backlink').count()===5,'References not capped');
    await page.locator('.backlinks>.link').click();assert(await page.locator('.backlink').count()===7,'All references inaccessible');
    const link=page.locator('.wiki-article [data-wiki="glossary"]').first();assert(await link.innerText()==='Project glossary','Readable link title absent');
    assert(await page.locator('.wiki-article [data-wiki="glossary"]').nth(1).innerText()==='Explicit alias','Alias changed');
    await page.locator('.wiki-article [data-wiki-scope="global"]').click();
    await page.locator('.wiki-doc-title').filter({hasText:'Shared agreements'}).waitFor();
    await page.goBack();await page.locator('.wiki-doc-title').filter({hasText:'Getting started'}).waitFor();
    await page.reload();await page.locator('.wiki-doc-title').filter({hasText:'Getting started'}).waitFor();
    await page.screenshot({path:`/tmp/wiki-makeover-article-${lang}.png`});
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');
    await page.screenshot({path:`/tmp/wiki-makeover-dark-${lang}.png`,animations:"disabled"});
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    for(const width of [390,768,1024]) {
      await page.setViewportSize({width,height:900});
      assert(await page.locator('.wiki-view').evaluate(el=>el.scrollWidth<=el.clientWidth),'Knowledge base overflows');
      if(width===390) {
        await page.locator('.wiki-mobile-bar button').last().click();
        assert(await page.locator('.wiki-context').evaluate(el=>el.getBoundingClientRect().top < document.querySelector('.wiki-main').getBoundingClientRect().top),'Context not reachable above article');
        await page.screenshot({path:`/tmp/wiki-makeover-mobile-${lang}.png`});
        await page.locator('.wiki-toc button').first().click();
        await page.locator('.wiki-mobile-bar button').first().click();await page.locator('.wiki-row').first().waitFor({state:'visible'});
        await page.locator('.wiki-mobile-bar button').first().click();
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('.wiki-actions').getByRole('button',{name:lang==='en'?'Edit':'Bewerken',exact:true}).click();
    await page.locator('.wiki-editor textarea').fill('My unsaved draft');
    await page.locator('.wiki-editor .wiki-field input').fill('Draft title');
    await page.locator('.wiki-editor-head').click();assert(writes.length===0,'Blur saved draft');
    await page.getByRole('button',{name:lang==='en'?'Board':'Bord',exact:true}).first().click();
    await page.getByRole('alertdialog').waitFor();
    await page.getByRole('button',{name:lang==='en'?'Keep editing':'Verder bewerken',exact:true}).click();
    assert(await page.locator('.wiki-editor textarea').inputValue()==='My unsaved draft','Draft lost on cancelled navigation');
    await page.goBack();await page.getByRole('alertdialog').waitFor();
    await page.getByRole('button',{name:lang==='en'?'Keep editing':'Verder bewerken',exact:true}).click();
    assert(await page.locator('.wiki-editor textarea').inputValue()==='My unsaved draft','History navigation lost draft');
    assert(new URL(page.url()).searchParams.get('wikiPage')==='getting-started','Cancelled history left wrong URL');
    conflict=true;await page.locator('.wiki-editor-actions .primary').click();await page.locator('.wiki-conflict').waitFor();
    assert(await page.locator('.wiki-editor textarea').inputValue()==='My unsaved draft','Conflict lost draft');
    await page.getByRole('button',{name:lang==='en'?'Compare with saved page':'Vergelijk met opgeslagen pagina',exact:true}).click();
    assert((await page.locator('.wiki-conflict').innerText()).includes('Concurrent saved content'),'Saved content cannot be compared');
    await page.getByRole('button',{name:lang==='en'?'Discard draft and reload':'Concept verwerpen en herladen',exact:true}).click();
    await page.getByRole('button',{name:lang==='en'?'Discard changes':'Wijzigingen verwerpen',exact:true}).click();
    await page.locator('.wiki-article').filter({hasText:'Concurrent saved content'}).waitFor();
    await page.locator('.wiki-actions').getByRole('button',{name:lang==='en'?'Edit':'Bewerken',exact:true}).click();
    await page.locator('.wiki-editor textarea').fill(body+'\n\nUpdated knowledge.');
    await page.locator('.wiki-editor').getByRole('radio',{name:lang==='en'?'Preview':'Voorbeeld',exact:true}).click();
    assert(await page.locator('.md-editor-preview [data-wiki="glossary"]').first().innerText()==='Project glossary','Wiki preview uses wrong renderer');
    await page.locator('.wiki-editor').getByRole('radio',{name:'Editor',exact:true}).click();
    await page.locator('.wiki-editor-actions .primary').click();await page.locator('.wiki-article').filter({hasText:'Updated knowledge.'}).waitFor();
    assert(writes.at(-1).expected_revision==='concurrent','Save did not use latest base');
    await page.locator('.wiki-menu-wrap>.icon-btn').click();
    await page.getByRole('button',{name:lang==='en'?'Protect knowledge':'Kennis beschermen',exact:true}).click();
    await page.locator('.wiki-protected').waitFor();assert(protection>0,'Protection action missing');
    await page.locator('.wiki-menu-wrap>.icon-btn').click();await page.getByRole('button',{name:lang==='en'?'History':'Geschiedenis',exact:true}).click();
    await page.locator('.rev-list button').click();await page.locator('.rev-view').waitFor();
    await page.getByRole('button',{name:lang==='en'?'Close diff':'Diff sluiten',exact:true}).click();
    await page.locator('.wiki-menu-wrap>.icon-btn').click();await page.getByRole('button',{name:lang==='en'?'Delete':'Verwijderen',exact:true}).click();
    assert(deletions===0,'Deletion bypassed confirmation');
    await page.getByRole('alertdialog').getByRole('button',{name:lang==='en'?'Cancel':'Annuleren',exact:true}).click();
    await page.locator('.wiki-new').click();
    await page.locator('.wiki-editor .wiki-field input').first().fill('New guide');
    await page.locator('.wiki-editor textarea').fill('New knowledge');
    await page.locator('.wiki-editor-actions .primary').click();await page.locator('.wiki-doc-title').filter({hasText:'New guide'}).waitFor();
    await page.locator('.wiki-breadcrumb button').click();await page.locator('.wiki-home').waitFor();
    failLoad=true;await page.reload();await page.getByRole('alert').waitFor();failLoad=false;
    await page.locator('.error-note-retry').click();await page.locator('.wiki-home').waitFor();
    pages.find(p=>p.slug==='getting-started').protected=true;actorKind='agent';
    await page.goto(`${base}/DEMO?view=wiki&wikiScope=project&wikiPage=getting-started&language=${lang}`);
    await page.locator('.wiki-doc-title').waitFor();
    await page.locator('.wiki-actions').getByRole('button',{name:lang==='en'?'Edit':'Bewerken',exact:true}).click();
    await page.locator('.wiki-editor textarea').fill('Proposed knowledge');
    await page.locator('.wiki-editor-actions .primary').click();
    await page.locator('.wiki-notice').waitFor();
    assert(pages.find(p=>p.slug==='getting-started').body_md.includes('Updated knowledge.'),'Protected content overwritten');
    assert((await page.locator('.wiki-notice').innerText()).includes(lang==='en'?'human review':'menselijke beoordeling'),'Proposal status missing');
    archived=true;actorKind='human';
    await page.reload();await page.locator('.wiki-doc-title').waitFor();
    assert(await page.locator('.wiki-actions').getByRole('button',{name:lang==='en'?'Edit':'Bewerken',exact:true}).isDisabled(),'Archived edit enabled');
    assert(await page.locator('.wiki-new').isDisabled(),'Archived create enabled');
    archived=false;pages=[];
    await page.goto(`${base}/DEMO?view=wiki&wikiScope=project&language=${lang}`);
    await page.locator('.wiki-home').waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('.wiki-row').length===0);
    assert(await page.locator('.wiki-row').count()===0,'Empty list incorrect');
    assert((await page.locator('.wiki-home-intro').innerText()).includes('0'),'Empty state missing count');
    console.log(lang+': home/search/outline/links/history/draft/conflict/save/create/proposal/readonly/empty passed');
  }
  assert(errors.length===0,errors.join('\n'));
}
