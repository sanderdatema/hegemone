import { afterEach, expect, it } from 'vitest';
import { render } from 'svelte/server';
import WebhookTest from './WebhookTest.svelte';
import { setLocale } from './lib/i18n.js';
import { webhookTestState, canTestWebhook } from './lib/webhookTest.js';
const user={handle:'receiver',kind:'agent',active:true,has_webhook:true,is_virtual:false};
afterEach(()=>setLocale('en'));
it('biedt alleen actieve echte agents met opgeslagen webhook een test aan',()=>{
  expect(canTestWebhook(user)).toBe(true);
  for(const patch of [{active:false},{has_webhook:false},{is_virtual:true},{kind:'human'}]) expect(canTestWebhook({...user,...patch})).toBe(false);
});
it('meldt geen succes zolang de dispatcher pending of retry boekt',()=>{
  expect(webhookTestState({status:'pending',attempts:0})).toBe('queued');
  expect(webhookTestState({status:'pending',attempts:1})).toBe('retrying');
  expect(webhookTestState({status:'delivered'})).toBe('delivered');
  expect(webhookTestState({status:'cancelled'})).toBe('cancelled');
});
it.each([['en','Test saved webhook'],['nl','Opgeslagen webhook testen']])('rendert %s zonder automatische succesclaim', (language,label)=>{
  setLocale(language);const body=render(WebhookTest,{props:{user}}).body;
  expect(body).toContain(label);expect(body).not.toContain('Test delivered successfully');
  expect(body).not.toContain('Test succesvol afgeleverd');
});
