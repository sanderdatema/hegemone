// Engelse eventpresentatie; waarden en tekstinhoud uit payloads blijven letterlijk.
const to = value => value && typeof value === 'object' && 'to' in value ? value.to : value;
const from = value => value && typeof value === 'object' && 'from' in value ? value.from : undefined;
const dash = value => value == null || value === '' ? '—' : value;
const workload = value => ({light:'light',medium:'medium',heavy:'heavy'})[value] ?? dash(value);

export function describeEventEnglish(event) {
  const p = event.payload || {};
  if (event.type === 'item.updated') {
    const parts = [];
    if (p.reason === 'deferred_expired') parts.push('deferral expired');
    for (const [field, label, format] of [['state','state',dash], ['priority','priority',dash], ['workload','workload',workload]]) {
      if (field in p) parts.push(`${label}: ${format(from(p[field]))} → ${format(to(p[field]))}`);
    }
    if ('assignee' in p) parts.push(to(p.assignee) ? `assigned to @${to(p.assignee)}` : 'assignment cleared');
    if ('title' in p) parts.push('title changed');
    if ('description_md' in p) parts.push('description changed');
    if ('parent' in p) parts.push(to(p.parent) ? `parent → ${to(p.parent)}` : 'parent unlinked');
    if ('milestone' in p) parts.push(to(p.milestone) ? `milestone → ${to(p.milestone)}` : 'milestone cleared');
    if ('labels' in p) parts.push(to(p.labels)?.length ? `labels: ${to(p.labels).join(', ')}` : 'labels cleared');
    if ('plan_md' in p) parts.push(p.plan_md?.cleared ? 'plan cleared' : 'plan updated');
    return parts.join(', ') || 'updated';
  }
  const simple = {
    'item.created':'ticket created', 'item.archived':'archived', 'item.restored':'restored from archive',
    'item.deleted':'deleted', 'question.answered':'answered the question',
    'item.guardrail_set':'set a guardrail', 'item.guardrail_lifted':'lifted the guardrail',
    'item.guardrail_rejected':'rejected the guardrail proposal',
    'comment.created':'commented', 'comment.updated':'comment edited', 'comment.deleted':'comment deleted',
  };
  if (simple[event.type]) return simple[event.type];
  switch (event.type) {
    case 'item.moved': return p.from ? `moved from ${p.from} to ${p.to}` : `moved to ${p.to}`;
    case 'item.locked': return p.reason === 'comment_limit' ? 'locked the ticket — too many comments' : 'locked the ticket (emergency stop)';
    case 'item.unlocked': return p.headroom ? `unlocked the ticket — room for ${p.headroom} comments` : 'unlocked the ticket';
    case 'item.guardrail_proposed': return p.guardrail?.proposal === 'lift' ? 'proposed lifting the guardrail' : 'proposed a guardrail';
    case 'wiki.compiled': return p.skipped || !Array.isArray(p.pages) || !p.pages.length ? 'wiki compilation skipped' : `wiki updated: ${p.pages.join(', ')}`;
    case 'relation.created': return `relation added: ${p.type} ${p.target}`;
    case 'relation.deleted': return `relation removed: ${p.type} ${p.target}`;
    default: return event.type;
  }
}
