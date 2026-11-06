// Widgetflow met synthetische deliverystatus; geen echte ontvanger.
export default async function webhookTest(page,base='http://127.0.0.1:8168') {
  await page.goto('about:blank');
  let posts=0, userLoads=0, mode='delivered';const deliveries={},polls={};
  const me={id:1,handle:'operator',display_name:'Operator',kind:'human',active:true,credential_policy:{scopes:['read','write','admin','llm']}};
  const receiver={id:2,handle:'receiver',display_name:'Receiver',kind:'agent',agent_type:'hermes',active:true,has_webhook:true};
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');let data=[];
    if(path==='/setup')data={required:false,enabled:false};
    else if(path==='/session')data={user:me,csrf_token:'fixture'};
    else if(path==='/me')data=me;
    else if(path==='/onboarding')data={required:false,step:'complete',locale:'en'};
    else if(path==='/projects')data=[{key:'TEAM',name:'Team'}];
    else if(path==='/users'){userLoads++;data=[me,receiver,{...receiver,id:3,handle:'inactive',display_name:'Inactive receiver',active:false}];}
    else if(path.endsWith('/states'))data=[{name:'todo',group:'unstarted'}];
    else if(path.endsWith('/state-counts'))data={todo:0};
    else if(path==='/inbox')data={items:[],unread:0};
    else if(path==='/users/receiver/webhook-test'){
      posts++;const id=100+posts;deliveries[id]=mode;data={id,status:'pending',attempts:0,next_retry_at:null,http_status:null};
      return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify(data)});
    }else if(path.startsWith('/users/receiver/webhook-test/')){
      const id=Number(path.split('/').pop());polls[id]=(polls[id]||0)+1;const value=deliveries[id];
      data={id,status:value==='failed'&&polls[id]===1?'pending':value,attempts:value==='failed'?polls[id]===1?1:3:1,http_status:value==='failed'?500:null,next_retry_at:null};
    }
    if(path==='/events/stream')return route.fulfill({status:200,contentType:'text/event-stream',body:': heartbeat\n\n'});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.addInitScript(()=>{localStorage.setItem('betonning_key','synthetic-webhook-test-login');localStorage.setItem('hegemone_locale','en');});
  await page.goto(base);
  await page.getByRole('button',{name:'More actions',exact:true}).click();
  await page.getByRole('menuitem',{name:'Agents & users',exact:true}).click();
  const row=page.locator('.ag-item').filter({has:page.locator('.ag-handle',{hasText:'@receiver'})});
  await row.getByRole('button',{name:'Test saved webhook',exact:true}).waitFor();
  if(posts)throw new Error('Test verstuurd bij laden');
  const inactive=page.locator('.ag-item').filter({has:page.locator('.ag-handle',{hasText:'@inactive'})});
  if(await inactive.getByRole('button',{name:'Test saved webhook',exact:true}).isEnabled())throw new Error('Inactieve agent testbaar');
  await row.getByRole('button',{name:'Test saved webhook',exact:true}).click();
  await row.getByText('Test queued — awaiting delivery',{exact:true}).waitFor();
  await row.getByText('Test delivered successfully',{exact:true}).waitFor();
  if(userLoads>3)throw new Error('Agentbeheer blijft het gebruikersoverzicht herladen');
  await row.getByRole('button',{name:'Refresh test status',exact:true}).click();
  await row.getByText('Test delivered successfully',{exact:true}).waitFor();
  if(posts!==1)throw new Error('Statusrefresh verstuurt nieuwe test');
  mode='failed';await row.getByRole('button',{name:'Test saved webhook',exact:true}).click();
  await row.getByText(/Delivery failed; an automatic retry is pending/).waitFor();
  await row.getByText(/Test failed after the delivery attempts/).waitFor();
  await row.getByText(/Receiver returned HTTP 500/).waitFor();
  mode='cancelled';await row.getByRole('button',{name:'Test saved webhook',exact:true}).click();
  await row.getByText('Test cancelled — the target changed or was disabled',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await page.getByRole('button',{name:'Account (@operator)',exact:true}).click();
  await page.getByRole('menuitem',{name:/Nederlands/}).click();await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Meer acties',exact:true}).click();
  await page.getByRole('menuitem',{name:'Agents & gebruikers',exact:true}).click();
  mode='delivered';await row.getByRole('button',{name:'Opgeslagen webhook testen',exact:true}).click();
  await row.getByText('Test succesvol afgeleverd',{exact:true}).waitFor();
  await row.screenshot({path:'/tmp/hegemone-webhook-test-nl.png',animations:'disabled'});
  if(posts!==4)throw new Error('Onverwachte extra tests');
  await row.getByRole('button',{name:'Afleverdetails',exact:true}).click();
  await page.getByText('Nog geen webhook-leveringen.',{exact:true}).waitFor();
  return {testRequests:posts,userRequests:userLoads};
}
