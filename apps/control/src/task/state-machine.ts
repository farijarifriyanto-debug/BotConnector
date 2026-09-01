import { z } from 'zod';
import { TaskStateSchema } from '@botconnector/contracts';

type TaskState = z.infer<typeof TaskStateSchema>;

/**
 * Canonical Task state transition policy.
 *
 * PUBLIC (user/control-plane) transitions:
 *   draft → approved → queued → active → validating → ready → applying → done
 *
 * TERMINAL: done, cancelled, failed
 *
 * CANCELLATION allowed from any non-terminal state.
 * FAILED may be reached from any non-terminal state (internal error).
 *
 * States belonging to future subsystems (validating, ready, applying) are
 * defined and persisted here but their executors do NOT exist yet. The kernel
 * owns the transition contract; the HTTP API does NOT expose arbitrary status
 * injection.
 */

const VALID_STATES = new Set<string>(TaskStateSchema.options);

/**
 * Allowed transitions for Task lifecycle.
 * Keys = source state, values = set of valid target states.
 */
const TASK_TRANSITIONS: Record<string, Set<string>> = {
  draft:      new Set(['approved', 'cancelled', 'failed']),
  approved:   new Set(['queued', 'cancelled', 'failed']),
  queued:     new Set(['active', 'cancelled', 'failed']),
  active:     new Set(['validating', 'cancelled', 'failed']),
  validating: new Set(['ready', 'cancelled', 'failed']),
  ready:      new Set(['applying', 'cancelled', 'failed']),
  applying:   new Set(['done', 'cancelled', 'failed']),
  // Terminal states: no outgoing transitions
  done:       new Set(),
  cancelled:  new Set(),
  failed:     new Set(),
};

/**
 * Whether `from` → `to` is a valid Task state transition.
 */
export function canTransitionTask(from: TaskState, to: TaskState): boolean {
  if (!VALID_STATES.has(from) || !VALID_STATES.has(to)) return false;
  const allowed = TASK_TRANSITIONS[from];
  if (!allowed) return false;
  return allowed.has(to);
}

/**
 * Whether the target state is terminal (no outgoing transitions).
 */
export function isTerminalTaskState(state: TaskState): boolean {
  return state === 'done' || state === 'cancelled' || state === 'failed';
}

/**
 * Whether a state is a user-facing lifecycle command (not internal/executor).
 */
export function isPublicTaskCommand(target: TaskState): boolean {
  return target === 'approved' || target === 'queued' || target === 'cancelled';
}

/**
 * Allowed user-facing Task commands by source state.
 * Used by route handlers to validate which lifecycle commands are available.
 */
export function getPublicTaskCommands(state: TaskState): TaskState[] {
  const transitions = TASK_TRANSITIONS[state];
  if (!transitions) return [];
  return Array.from(transitions).filter((s) => isPublicTaskCommand(s as TaskState)) as TaskState[];
}
