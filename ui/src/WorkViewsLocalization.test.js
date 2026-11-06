import {afterEach, it, expect, vi} from 'vitest';
vi.mock('./DrawerDialog.svelte', async () => import('./WorkViewDialogFixture.svelte'));
import {render} from 'svelte/server';
import Inbox from './Inbox.svelte';
import TriageChat from './TriageChat.svelte';
import {setLocale, translate} from './lib/i18n.js';
import {groupNotifications, summarizeGroup, dueLabel, guardrailLabel, answeredLabel, agentUnreachableLabel} from './lib/inbox.js';

afterEach(() => setLocale('en'));
it('lokaliseert inboxsamenvattingen maar behoudt overdracht en antwoordinhoud', () => {
  expect(summarizeGroup({assigned:1,comment:2}, ['worker'], 'en')).toBe('1 assignment, 2 comments — @worker');
  const entry={ref:'TEAM-1',event_id:1,reason:'comment',actor:'worker',read:false,title:'Eigen titel',created_at:'2026-11-05T12:00:00Z'};
  expect(groupNotifications([entry], 'en')[0].summary).toBe('1 comment — @worker');
  expect(groupNotifications([{...entry,handover_md:'Originele overdracht'}], 'en')[0].summary).toBe('Originele overdracht');
  expect(answeredLabel({options:['Eigen antwoord'],answeredIndex:0},'en')).toBe('Answered: Eigen antwoord');
  expect(dueLabel({reason:'due',overdue:true,due_date:'2026-11-01'},'en')).toBe('overdue (2026-11-01)');
  expect(guardrailLabel({reason:'guardrail',proposal_kind:'lift'},'en')).toBe('proposed lifting the guardrail');
  expect(agentUnreachableLabel({reason:'agent_unreachable',failed_count:2,created_at:'2026-11-01T12:00:00Z'},'en')).toBe('2 deliveries failed since 2026-11-01');
});
it('rendert inbox en triagechat in beide talen', () => {
  setLocale('en');
  expect(render(Inbox).body).toContain('Mark all as read');
  expect(render(Inbox).body).toContain('Nothing new.');
  expect(render(TriageChat).body).toContain('Chat with triage');
  expect(render(TriageChat).body).toContain('Ask a question or give an instruction.');
  setLocale('nl');
  expect(render(Inbox).body).toContain('Alles gelezen');
  expect(render(TriageChat).body).toContain('Chat met triage');
  expect(translate('en','triage.confirmCount',{count:42})).toContain('42');
});

import Wiki from './Wiki.svelte';

it('rendert wikinavigatie in beide talen en houdt slugs en titels letterlijk', () => {
  setLocale('en');
  const english = render(Wiki, {props:{project:'TEAM',projectName:'Eigen project',me:{kind:'agent'}}}).body;
  expect(english).toContain('New page');
  expect(english).toContain('Choose a page');
  expect(english).toContain('Search title or content');
  expect(english).toContain('Eigen project');
  expect(translate('en','wiki.deleteQuestion',{slug:'eigen-slug'})).toBe('Delete eigen-slug?');
  expect(translate('en','wiki.reviewNote',{slug:'eigen-slug'})).toContain('eigen-slug');
  setLocale('nl');
  expect(render(Wiki, {props:{me:{kind:'agent'}}}).body).toContain('Kies een pagina');
});

import Activity from './Activity.svelte';
import Overview from './Overview.svelte';
import ListView from './ListView.svelte';
import {describeEvent} from './lib/board.js';
import {countsText} from './lib/overview.js';

it('vertaalt werkviews en behoudt ticketwaarden en actoridentiteit', () => {
  setLocale('en');
  expect(render(Activity,{props:{project:'TEAM',projectName:'Eigen project'}}).body).toContain('Activity — Eigen project');
  expect(render(Overview).body).toContain('All projects');
  const list = render(ListView,{props:{items:[{ref:'TEAM-1',title:'Eigen titel',state:'Eigen status',labels:[]}]}}).body;
  expect(list).toContain('Assigned to');
  expect(list).toContain('Eigen titel');
  expect(list).toContain('Eigen status');
  expect(countsText({in_progress:2,open_questions:1,unread:3},'en')).toBe('2 in progress · 1 question · 3 unread');
  const event={type:'item.updated',payload:{state:{from:'Eigen status',to:'done'},assignee:{to:'worker'},title:{to:'Private title'},plan_md:{changed:true}}};
  expect(describeEvent(event,'en')).toBe('state: Eigen status → done, assigned to @worker, title changed, plan updated');
  expect(describeEvent(event,'en')).not.toContain('Private title');
  expect(describeEvent({type:'item.guardrail_proposed',payload:{guardrail:{proposal:'lift'}}},'en')).toBe('proposed lifting the guardrail');
  expect(describeEvent({type:'unknown.event'},'en')).toBe('unknown.event');
  setLocale('nl');
  expect(render(Activity,{props:{project:'TEAM'}}).body).toContain('Activiteit');
});

it('houdt commandopalet en eventwaarden taalagnostisch', () => {
  expect(translate('en','palette.project',{key:'TEAM',name:'Eigen naam'})).toBe('Go to project TEAM — Eigen naam');
  expect(translate('nl','palette.assign',{handle:'worker'})).toBe('Toewijzen → @worker');
  expect(describeEvent({type:'relation.created',payload:{type:'blocked_by',target:'TEAM-2'}},'en')).toBe('relation added: blocked_by TEAM-2');
});

import {propertySummary,railProperties,followChoices,selfFollowState,followChoiceOps} from './lib/drawerLogic.js';
import ConfirmBar from './ConfirmBar.svelte';

it('vertaalt ticketrail en volglabels met behoud van waarden en volgacties', () => {
  expect(propertySummary({}, {locale:'en'})).toMatchObject({assignee:'unassigned',due:'no date',milestone:'no milestone'});
  const rows=railProperties({due_date:'2026-11-05',milestone:'Eigen milestone'}, {locale:'en',milestones:[{name:'Eigen milestone'}]});
  expect(rows.find(row=>row.key==='due')).toMatchObject({label:'Due date',text:'2026-11-05'});
  expect(rows.find(row=>row.key==='milestone').text).toBe('Eigen milestone');
  expect(followChoices('en').map(row=>row.value)).toEqual(followChoices('nl').map(row=>row.value));
  expect(selfFollowState({following:true},'en')).toEqual({state:'following',label:'Following'});
  expect(followChoiceOps('mute',{following:true})).toEqual(['mute']);
  setLocale('en');
  const rendered=render(ConfirmBar,{props:{onconfirm:()=>{},oncancel:()=>{}}}).body;
  expect(rendered).toContain('Confirm');
  expect(rendered).toContain('Cancel');
  expect(translate('en','detail.answer',{answer:'Eigen antwoord'})).toBe('Answer with “Eigen antwoord”?');
});

it('lokaliseert vraagafzenders met behoud van de exacte handle', () => {
  expect(translate('en','detail.questionFrom',{author:'team-agent'})).toBe('Question from @team-agent');
  expect(translate('nl','detail.questionFrom',{author:'team-agent'})).toBe('Vraag van @team-agent');
  expect(translate('en','settings.saveModelsFailed')).toBe('Could not save model mappings.');
});

it('vertaalt bulkbevestiging en duplicaatdiagnose zonder refs te wijzigen', () => {
  expect(translate('en','triage.exactCount',{count:42})).toBe('Type the exact count (42) to confirm.');
  expect(translate('en','detail.duplicateNoCancelled',{ref:'TEAM-9',project:'TEAM'})).toContain('Duplicate TEAM-9: project TEAM');
  expect(translate('en','detail.duplicateCancelFailed',{ref:'TEAM-9',cause:'503'})).toContain('TEAM-9 automatically: 503');
});

it('vertaalt kaart-, bulk- en tijdlijnlabels met behoud van parameters', () => {
  expect(translate('en','board.childrenProgress',{done:1,total:3})).toBe('1 of 3 subtasks completed');
  expect(translate('nl','board.childrenProgress',{done:1,total:3})).toBe('1 van 3 subtaken afgerond');
  expect(translate('en','board.selectColumn',{column:'Eigen kolom'})).toBe('Select all in Eigen kolom');
  expect(translate('en','detail.answeredBy',{author:'team-agent'})).toBe('Answered by @team-agent');
  expect(translate('en','bulk.selected',{count:7})).toBe('7 selected');
});
