"""Stable execution error identifiers and server-language lifecycle messages."""
from .outbound import outbound


_CODES = {
    'Execution authorization required': 'authorization_required',
    'An active, non-virtual agent is required': 'agent_required',
    'Execution belongs to another identity': 'identity_mismatch',
    'Execution owner or fence is stale': 'owner_stale',
    'Execution identity or profile does not match': 'profile_mismatch',
    'Assignment or human input prevents execution': 'assignment_blocked',
    'Read the full current task and plan before claiming': 'context_changed',
    'Required capabilities were not verified': 'capabilities_missing',
    'Another owner holds the claim': 'claim_held',
    'Execution is not ready to claim': 'not_ready',
    'Execution owner proof is required': 'owner_proof_required',
    'Execution was changed, blocked or revoked': 'context_revoked',
    'External run identity changed': 'run_mismatch',
    'Project has no executable started state': 'started_state_missing',
    'Execution must stop; no new work is authorized': 'stop_required',
    'Explicit recovery is required for a lost execution owner': 'recovery_required',
    'Execution is no longer active': 'not_active',
    'Transport retries after execution require explicit recovery': 'transport_recovery_required',
    'Use the existing human question workflow first': 'question_required',
    'Execution is not blocked': 'not_blocked',
    'Confirm the prior worker stopped and previous effects were reviewed': 'recovery_confirmation',
    'Assignment or human input prevents resuming': 'resume_assignment_blocked',
    'Completion evidence cannot be changed after completion': 'evidence_immutable',
    'Only a live running execution can declare completion with evidence': 'completion_required',
    'Executor identity was revoked': 'identity_revoked',
    'Task is archived or locked': 'archived_locked',
    'Task no longer exists': 'no_task',
    'Task state does not permit execution': 'state_blocked',
    'Executor is disabled or its identity is no longer authorized': 'executor_disabled',
    'Executor lacks project assignment or credential permission': 'project_permission',
    'Task is blocked by another ticket or marked as a duplicate': 'relation_blocked',
    'Execution owner was lost; previous effects are unknown': 'owner_lost',
    'A human must confirm the old worker stopped and review previous effects': 'owner_recovery',
    'A human answer is required': 'human_answer',
    'Assignment or task revision changed': 'source_changed',
    'The current owner must stop and acknowledge before another claim': 'owner_ack_required',
    'Answer or withdraw the existing human question': 'answer_existing',
    'Restore the relevant execution permission or workflow prerequisite': 'permission_resume',
    'Assignment changed': 'assignment_changed',
    'Resolve the existing human question or workflow prerequisite': 'question_or_policy',
    'Executor acknowledged it stopped': 'owner_stopped',
}


def code_for(message: str) -> str:
    key = _CODES.get(message)
    if key is None:
        for candidate in _CODES.values():
            if message == outbound("execution." + candidate):
                key = candidate
                break
    return "execution_" + key if key else "execution_conflict"


def message(key: str) -> str:
    return outbound("execution." + key)
