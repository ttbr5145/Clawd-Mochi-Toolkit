export const name = 'clawd-mochi-dsh-status-ext';

/**
 * Richer DeepSeek Harness -> Clawd-Mochi bridge.
 *
 * The stock plugin shipped with the control center maps 5 harness moments onto
 * 7 pet states.  DSH's plugin API exposes more: tool calls, approval prompts,
 * sub-agent lifecycle, errors, lifecycle.  This plugin forwards them as *rich*
 * events (event + text) to the extended bridge on 18894, which turns the text
 * into the pet's terminal view and keeps the normal eye animation working.
 *
 * Install: point the `clawd-mochi-status` entry in
 *   %USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml
 * at this file (it is a drop-in replacement), e.g.
 *
 *   - id: clawd-mochi-status
 *     name: C:/path/to/ext/dsh-plugin/index.js
 *
 * If the extended bridge is not running it falls back to the stock bridge on
 * 18892 so the pet still works.
 */

const EXT = 'http://127.0.0.1:18894/event';
const STOCK = 'http://127.0.0.1:18892/event?s=';
const STOCK_STATES = new Set(['idle', 'thinking', 'coding', 'waiting', 'done', 'error', 'sleep']);

function short(value, max = 60) {
  if (value === undefined || value === null) return '';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

function toolLabel(event) {
  const d = event?.data ?? {};
  const name = d.name ?? d.tool ?? d.toolName ?? d.id ?? d.kind ?? '';
  const input = d.input ?? d.args ?? d.parameters ?? d.input_preview ?? '';
  const detail = short(input, 60);
  return [name, detail].filter(Boolean).join(' ').trim();
}

function approvalLabel(event) {
  const d = event?.data ?? {};
  const what = d.command ?? d.path ?? d.pattern ?? d.description ?? d.reason ?? d.tool ?? '';
  return short(what, 70);
}

export function createStatusBridge(emit) {
  const agents = new Map();
  const sessions = new Map();

  function record(agent) {
    if (!agents.has(agent)) agents.set(agent, { error: false, waiting: 0, running: false });
    return agents.get(agent);
  }

  function anyWaiting() {
    return [...agents.values()].some((item) => item.running && item.waiting > 0);
  }

  function anyRunning() {
    return [...agents.values()].some((item) => item.running);
  }

  return {
    onCreated({ agent }) {
      sessions.set(agent.session, agent);
      emit('thinking', { label: 'session' });
    },

    onStatus({ agent, status }) {
      const item = record(agent);
      if (status === 'running') {
        item.error = false;
        item.waiting = 0;
        item.running = true;
        emit(anyWaiting() ? 'waiting' : 'thinking');
      } else if (status === 'idle') {
        item.running = false;
        const state = anyWaiting() ? 'waiting' : anyRunning() ? 'coding' : item.error ? 'error' : 'done';
        emit(state, { label: 'done' });
        agents.delete(agent);
      }
    },

    onError({ agent }) {
      record(agent).error = true;
      emit('error');
    },

    onSessionEvent(session, event) {
      const agent = sessions.get(session);
      const type = event?.type ?? '';
      if (type === 'approval/asked') {
        if (agent) record(agent).waiting += 1;
        emit('waiting', { text: approvalLabel(event), label: 'confirm' });
      } else if (type === 'approval/decided') {
        if (agent) record(agent).waiting = Math.max(0, record(agent).waiting - 1);
        if (event?.data?.outcome === 'rejected') {
          if (agent) record(agent).error = true;
          emit('error', { text: 'rejected' });
        } else {
          emit(anyWaiting() ? 'waiting' : 'coding');
        }
      } else if (type === 'tool/call') {
        if (!anyWaiting()) emit('coding', { text: toolLabel(event), label: 'tool' });
      } else if (type === 'subagent/start' || type === 'agent/created') {
        emit('delegating', { text: short(event?.data?.name ?? '', 40), label: 'sub' });
      } else if (type === 'compaction') {
        emit('compacting');
      }
    },

    onDisposed({ agent }) {
      agents.delete(agent);
      sessions.delete(agent.session);
    },
  };
}

export function apply(ctx, config = {}) {
  void config;
  const send = (event, extra = {}) => {
    const params = new URLSearchParams({ e: event, ...extra });
    fetch(`${EXT}?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
      })
      .catch(() => {
        // extended bridge down -> keep the stock behaviour
        if (STOCK_STATES.has(event)) fetch(STOCK + encodeURIComponent(event)).catch(() => {});
      });
  };

  const emit = (event, extra = {}) => send(event, extra);
  const bridge = createStatusBridge(emit);
  ctx.on('agent/created', bridge.onCreated);
  ctx.on('agent/status', bridge.onStatus);
  ctx.on('agent/error', bridge.onError);
  ctx.on('session/event', bridge.onSessionEvent);
  ctx.on('agent/disposed', bridge.onDisposed);
}
