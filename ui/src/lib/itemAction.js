// Prefer factual waiting states over assignment; delivery alone is never execution.
export function itemAction(item, {virtualHandles = new Set()} = {}) {
  if (!item || item.archived_at || item.locked || item.locked_at) return null;
  const signals = item.work_signals || {};
  if (signals.closed) return null;
  if (signals.question_for_viewer) return {key:'action.yourAnswer', params:{}};
  if (item.has_open_question) return {key:'action.answer', params:{}};
  if (signals.blocked_by?.length) return {key:'action.blockedBy', params:{refs:signals.blocked_by.join(', ')}};
  const execution = item.execution || signals.execution;
  if (execution && ['blocked', 'stopping'].includes(execution.status)) return {
    key: execution.status === 'stopping' ? 'action.stopping' : 'action.blocked', params:{},
    reason: execution.reason, responsible: execution.responsible, condition: execution.resume_condition,
  };
  if (execution && ['pending','claimed','running'].includes(execution.status)) return {key:`action.${execution.status}`, params:{}};
  if (item.assignee && virtualHandles.has(item.assignee)) return {key:'action.queue', params:{queue:item.assignee}};
  return null;
}
