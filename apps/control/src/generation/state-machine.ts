import { z } from 'zod';
import { GenerationStateSchema } from '@botconnector/contracts';

type GenerationState = z.infer<typeof GenerationStateSchema>;

/**
 * Canonical GenerationRun state transition policy.
 *
 * PUBLIC (user/control-plane) transitions:
 *   planning → running → pausing → paused → running  (resume)
 *   running/pausing/paused → stopping → stopped
 *
 * INTERNAL (executor/future) transitions:
 *   pausing → paused  (executor safe-point acknowledgement)
 *   stopping → stopped (executor safe-point acknowledgement)
 *
 * TERMINAL: completed, failed, stopped
 *
 * States belonging to future subsystems (validating, repairing) are
 * defined and persisted here but their executors do NOT exist yet.
 */

const VALID_STATES = new Set<string>(GenerationStateSchema.options);

/**
 * Allowed transitions for GenerationRun lifecycle.
 */
const GENERATION_TRANSITIONS: Record<string, Set<string>> = {
  planning:  new Set(['running', 'failed']),
  running:   new Set(['pausing', 'stopping', 'failed']),
  pausing:   new Set(['paused', 'stopping', 'failed']),
  paused:    new Set(['running', 'stopping', 'failed']),
  stopping:  new Set(['stopped', 'failed']),
  stopped:   new Set(),
  validating: new Set(['completed', 'failed']),
  repairing: new Set(['completed', 'failed']),
  completed: new Set(),
  failed:    new Set(),
};

/**
 * Whether `from` → `to` is a valid GenerationRun state transition.
 */
export function canTransitionGenerationRun(from: GenerationState, to: GenerationState): boolean {
  if (!VALID_STATES.has(from) || !VALID_STATES.has(to)) return false;
  const allowed = GENERATION_TRANSITIONS[from];
  if (!allowed) return false;
  return allowed.has(to);
}

/**
 * Whether the target state is terminal.
 */
export function isTerminalGenerationState(state: GenerationState): boolean {
  return state === 'completed' || state === 'failed' || state === 'stopped';
}

/**
 * Whether a transition is an executor-only acknowledgement
 * (safe-point completion for pause or stop).
 */
export function isExecutorOnlyTransition(from: GenerationState, to: GenerationState): boolean {
  return (from === 'pausing' && to === 'paused') ||
         (from === 'stopping' && to === 'stopped');
}

/**
 * Public control-plane commands that users can invoke.
 */
export function isPublicGenerationCommand(target: GenerationState): boolean {
  return target === 'pausing' || target === 'stopping';
}
