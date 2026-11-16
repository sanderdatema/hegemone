import {describe,it,expect} from 'vitest';
import {itemAction} from './itemAction.js';
describe('factual next action',()=>{
  it('prioritizes directed human questions above blockers and queue assignment',()=>{
    expect(itemAction({has_open_question:true,assignee:'queue',work_signals:{question_for_viewer:true,blocked_by:['DEMO-2']}},{virtualHandles:new Set(['queue'])}).key).toBe('action.yourAnswer');
    expect(itemAction({has_open_question:true,work_signals:{question_for_viewer:false}}).key).toBe('action.answer');
  });
  it('uses only active blocker signals and real execution state',()=>{
    expect(itemAction({relations:{blocked_by:['DEMO-2']},work_signals:{blocked_by:[]}})).toBeNull();
    expect(itemAction({work_signals:{blocked_by:['DEMO-3']}}).params.refs).toBe('DEMO-3');
    expect(itemAction({last_delivery_at:'now'})).toBeNull();
    expect(itemAction({work_signals:{execution:{status:'running'}}}).key).toBe('action.running');
  });
  it('preserves blocker owner/condition and recognizes only known virtual queues',()=>{
    const execution={status:'blocked',reason:'Missing capability',responsible:'person',resume_condition:'Configure access'};
    expect(itemAction({execution})).toMatchObject({key:'action.blocked',reason:execution.reason,responsible:'person',condition:'Configure access'});
    expect(itemAction({assignee:'queue'},{virtualHandles:new Set(['queue'])}).key).toBe('action.queue');
    expect(itemAction({assignee:'agent'})).toBeNull();
  });
  it('does not offer work on closed, archived or locked tickets',()=>{
    for(const extra of [{work_signals:{closed:true}},{archived_at:'now'},{locked:true}])expect(itemAction({has_open_question:true,...extra})).toBeNull();
  });
});
