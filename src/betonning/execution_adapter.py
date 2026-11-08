"""HTTP executor client and native worker tool gate; no automatic runtime setup.

The host supplies credentials and a real capability probe. Credentials/owner
proofs never enter the native task body, tool arguments or model messages.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import threading
from urllib.parse import quote

import httpx


class AdapterError(RuntimeError):
    pass


class ExecutionAPI:
    def __init__(self, base_url: str, api_key: str, execution_key: str, *, client=None):
        url = httpx.URL(base_url)
        if url.scheme not in ('http','https') or not url.host or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use an explicit application URL without credentials, query or fragment')
        self.base_url = str(url).rstrip('/')
        self._headers = {'Authorization':f'Bearer {api_key}','X-Execution-Key':execution_key}
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=10,follow_redirects=False)

    def close(self):
        if self._owned_client:
            self._client.close()

    def request(self, method, path, body=None, *, nonce=None):
        headers = dict(self._headers)
        if nonce is not None:
            headers['X-Execution-Owner']=nonce
        response = self._client.request(method,self.base_url+'/api/v1'+path,
                                        json=body,headers=headers,follow_redirects=False)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def path(context, action=''):
        ref=quote(context['item']['ref'],safe='')
        request_id=quote(context['execution']['id'],safe='')
        return f'/items/{ref}/executions/{request_id}'+('/'+action if action else '')

    def prepare(self, ref: str, request_id: str):
        return self.request('GET',f'/items/{quote(ref,safe="")}/executions/{quote(request_id,safe="")}')

    def claim(self, context, *, capabilities: set[str], owner: str, nonce: str, external_task_id=None):
        return self.request('POST',self.path(context,'claim'),{
            'profile':context['execution']['profile'],'context_digest':context['context_digest'],
            'capabilities_checked':sorted(capabilities),'task_read':True,'owner':owner,
            'external_task_id':external_task_id,
        },nonce=nonce)

    def start(self, context, fence: int, nonce: str, external_run_id: str):
        return self.request('POST',self.path(context,'start'),{
            'fence':fence,'context_digest':context['context_digest'],'external_run_id':external_run_id,
        },nonce=nonce)

    def heartbeat(self, context, fence: int, nonce: str):
        return self.request('POST',self.path(context,'heartbeat'),{'fence':fence},nonce=nonce)

    def stop(self, context, fence: int, nonce: str):
        return self.request('POST',self.path(context,'stop'),{'fence':fence},nonce=nonce)

    def complete(self, context, fence: int, nonce: str, evidence: list[dict]):
        return self.request('POST',self.path(context,'complete'),{'fence':fence,'evidence':evidence},nonce=nonce)

    def block(self, context, *, kind, reason, missing=(), responsible='administrator',
              resume_condition, fence=0, nonce=None, question_id=None):
        return self.request('POST',self.path(context,'block'),{
            'kind':kind,'reason':reason,'missing_requirements':list(missing),'responsible':responsible,
            'resume_condition':resume_condition,'fence':fence,'question_id':question_id,
        },nonce=nonce)


class ExecutionToolGuard:
    """Register as Hermes' fail-closed pre_tool_call hook for one native run.

    A host-created guard must be bound to the actual assigned profile, native
    task and native run. Never bind these from untrusted model/tool arguments.
    One lock serializes parallel first-tool claims; every later tool revalidates
    ownership. The host, not the model, supplies the capability probe.
    """
    def __init__(self, api, context, *, profile, capability_probe, owner, external_task_id, external_run_id, task_context_delivered=False):
        if profile!=context['execution']['profile']:
            raise AdapterError('Assigned native profile does not match the execution request')
        self.api,self.context,self.profile = api,context,profile
        self.capability_probe,self.owner = capability_probe,owner
        self.external_task_id,self.external_run_id = external_task_id,external_run_id
        self._context_delivered = task_context_delivered
        self._nonce = secrets.token_urlsafe(32)
        self._fence = None
        self._halted = False
        self._lock = threading.Lock()

    def register(self, plugin_context):
        plugin_context.register_hook('pre_tool_call',self.before_tool)

    def before_tool(self, tool_name, args=None, **kwargs):
        # Native read-only/lifecycle reporting remains possible when work must stop.
        if tool_name in ('kanban_show','kanban_block'):
            return None
        with self._lock:
            if not self._context_delivered:
                return {'action':'block','message':'The host must deliver the full current task, plan and prior attempts before execution.'}
            if self._halted:
                return {'action':'block','message':'Execution is stopped; resolve its recorded blocker before resuming.'}
            try:
                if self._fence is None:
                    fresh=self.api.prepare(self.context['item']['ref'],self.context['execution']['id'])
                    if fresh['context_digest']!=self.context['context_digest']:
                        raise AdapterError('Task changed after native staging; review the full current task and plan')
                    capabilities=set(self.capability_probe(self.profile))
                    missing=set(fresh['required_capabilities'])-capabilities
                    if missing:
                        self.api.block(fresh,kind='capability',reason='Native profile lacks required verified capabilities.',
                                       missing=sorted(missing),resume_condition='Verify the existing profile permissions before resuming.')
                        self._halted=True
                        return {'action':'block','message':'Required capabilities are unavailable; a durable blocker was recorded.'}
                    claimed=self.api.claim(fresh,capabilities=capabilities,owner=self.owner,nonce=self._nonce,
                                           external_task_id=self.external_task_id)
                    self._fence=claimed['fence']
                    self.api.start(fresh,self._fence,self._nonce,self.external_run_id)
                else:
                    self.api.heartbeat(self.context,self._fence,self._nonce)
                return None
            except Exception:
                # Never echo headers, credentials, provider stderr or task bodies.
                self._halted=True
                return {'action':'block','message':'Execution authorization could not be confirmed. Stop and inspect the execution status.'}

    def acknowledge_stopped(self):
        """Host calls only after joining in-flight tools / verifying worker exit."""
        with self._lock:
            self._halted=True
            if self._fence is not None:
                return self.api.stop(self.context,self._fence,self._nonce)
        return None

    def complete(self, evidence: list[dict]):
        """Host verifier supplies observed evidence, never a model's final text alone."""
        with self._lock:
            if self._halted or self._fence is None:
                raise AdapterError('No live execution may be completed')
            result=self.api.complete(self.context,self._fence,self._nonce,evidence)
            self._halted=True
            return result


def native_task_body(context) -> str:
    return json.dumps({
        'contract':'hegemone-execution-v1',
        'instruction':'Use the complete task, plan and prior attempts below. Do not execute until the trusted host tool gate confirms the current execution claim. Respect all existing profile approvals and tool restrictions.',
        'execution_id':context['execution']['id'],'profile':context['execution']['profile'],
        'context_digest':context['context_digest'],'item':context['item'],'plan_md':context['plan_md'],
        'comments':context['comments'],'attempts':context['attempts'],
    },ensure_ascii=False)


def native_stage_command(context, *, board: str, executable='hermes') -> list[str]:
    if context['execution']['status']!='pending':
        raise AdapterError('Only a pending execution may be staged')
    profile=context['execution']['profile']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',profile) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',board):
        raise AdapterError('Use explicit native profile and board identifiers')
    return [executable,'-p',profile,'kanban','--board',board,'create','--assignee',profile,
            '--body-file','-','--idempotency-key','hegemone:'+context['execution']['id'],
            '--initial-status','blocked','--max-retries','1','--json','--',context['item']['title']]


def stage_native(context, *, board: str, runner=subprocess.run, executable='hermes') -> dict:
    """Explicit operator action: create only a BLOCKED native card, not a worker.

    Installation/activation of the trusted tool guard and native lifecycle wiring
    is separate. This function never promotes a card, dispatches or restarts a
    gateway, changes a toolset or passes credentials on argv/stdin.
    """
    result=runner(native_stage_command(context,board=board,executable=executable),
                  input=native_task_body(context),text=True,capture_output=True,timeout=30,check=False)
    if result.returncode:
        raise AdapterError('Native staging failed; inspect the private native diagnostics')
    try:
        task=json.loads(result.stdout)
    except (ValueError,TypeError):
        raise AdapterError('Native staging did not return a task record') from None
    if not isinstance(task,dict) or not isinstance(task.get('id'),str):
        raise AdapterError('Native staging did not return a task identity')
    if task.get('status')!='blocked' or task.get('assignee')!=context['execution']['profile']:
        raise AdapterError('Existing native task is not safely parked for the assigned profile')
    return task
