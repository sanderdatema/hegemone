// Generiek webhookagentformulier met synthetische API-fixtures.
import languageNavigation from './language-navigation.js';
export default async function agentConfiguration(page) {
  await languageNavigation(page);
  let payload;
  const people = [{id:1,handle:'operator',display_name:'Operator',kind:'human',active:true}];
  await page.route('**/api/v1/users', async route => {
    if (route.request().method() === 'POST') {
      payload = route.request().postDataJSON();
      people.push({id:2,handle:payload.handle,display_name:payload.display_name,kind:'agent',agent_type:payload.agent_type,active:true,has_webhook:true});
      await route.fulfill({status:201,contentType:'application/json',body:JSON.stringify({...people[1],api_key:'synthetic-agent-key-fixture-only'})});
    } else await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(people)});
  });
  await page.getByRole('button', {name:'More actions',exact:true}).click();
  await page.getByRole('menuitem', {name:'Agents & users',exact:true}).click();
  await page.getByRole('heading', {name:'Agents & users',exact:true}).waitFor();
  await page.getByRole('button', {name:'New',exact:true}).click();
  await page.getByPlaceholder('worker',{exact:true}).fill('worker');
  await page.getByPlaceholder('Display name',{exact:true}).fill('Worker');
  await page.locator('.ag-create .select-trigger').nth(1).click();
  await page.getByRole('option', {name:'Webhook agent (Hermes compatible)',exact:true}).click();
  await page.getByPlaceholder('https://agent.example.org/events').fill('https://receiver.example.org/events');
  const secret = page.getByPlaceholder('Receiver HMAC secret');
  if(await secret.getAttribute('type') !== 'password') throw new Error('Secretveld niet afgeschermd');
  await secret.fill('synthetic-hmac-fixture-only');
  await page.getByRole('button',{name:'Create',exact:true}).click();
  await page.locator('.key-box').waitFor();
  if(payload?.agent_type !== 'hermes' || payload?.webhook_url !== 'https://receiver.example.org/events') throw new Error('Webhookconfiguratie niet behouden');
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.screenshot({path:'/tmp/hegemone-agent-configuration.png'});
}
