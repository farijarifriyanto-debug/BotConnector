import { describe, expect, it } from 'vitest';

import {
  AcceptanceContractSchema,
  BacklogItemSchema,
  EventFamilySchema,
  FocusLockSchema,
  GenerationEventSchema,
  GenerationEventPayloadSchema,
  GenerationRunSchema,
  GenerationStateSchema,
  PhaseSchema,
  RenderTransactionSchema,
  SteeringEventSchema,
  TaskSchema,
  TaskDependencySchema,
  TaskStateSchema,
  validateGenerationEventSequence,
} from '../src/index.js';

const timestamp = '2026-09-01T00:00:00.000Z';

const generationEvent = (sequence: number) => ({
  version: 1,
  id: `event-${sequence}`,
  sequence,
  project_id: 'project-1',
  correlation_id: 'correlation-1',
  causation_id: null,
  actor: {
    type: 'agent',
    id: 'agent-1',
  },
  timestamp,
  payload: {
    version: 1,
    family: 'transaction',
    transaction_id: 'transaction-1',
    state: 'validating',
  },
});

describe('work contracts', () => {
  it('exports every locked task state', () => {
    expect(TaskStateSchema.options).toEqual([
      'draft',
      'approved',
      'queued',
      'active',
      'validating',
      'ready',
      'applying',
      'done',
      'cancelled',
      'failed',
    ]);
  });

  it('accepts a valid Task', () => {
    const task = {
      version: 1,
      id: 'task-1',
      project_id: 'project-1',
      phase_id: 'phase-1',
      title: 'Build shared contracts',
      state: 'active',
      revision: '2',
      base_revision: '1',
      acceptance_contract_id: 'acceptance-1',
      created_at: timestamp,
      updated_at: timestamp,
    };

    expect(TaskSchema.parse(task)).toEqual(task);
  });

  it('validates phase, dependency, focus, backlog, and acceptance contracts', () => {
    expect(
      PhaseSchema.parse({
        version: 1,
        id: 'phase-1',
        project_id: 'project-1',
        ordinal: 1,
        name: 'Contracts Kernel',
        active: true,
        revision: '1',
        base_revision: '0',
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      TaskDependencySchema.parse({
        version: 1,
        id: 'dependency-1',
        project_id: 'project-1',
        task_id: 'task-2',
        depends_on_task_id: 'task-1',
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      FocusLockSchema.parse({
        version: 1,
        id: 'focus-1',
        project_id: 'project-1',
        task_id: 'task-1',
        scope: 'packages/contracts',
        owner_id: 'agent-1',
        revision: '1',
        base_revision: '0',
        acquired_at: timestamp,
        expires_at: null,
      }),
    ).toBeDefined();
    expect(
      BacklogItemSchema.parse({
        version: 1,
        id: 'backlog-1',
        project_id: 'project-1',
        title: 'Add persistence',
        description: 'Deferred to Phase 2',
        target_phase: 'PHASE_2_POSTGRESQL_CONTROL_PLANE',
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      AcceptanceContractSchema.parse({
        version: 1,
        id: 'acceptance-1',
        project_id: 'project-1',
        task_id: 'task-1',
        revision: '1',
        base_revision: '0',
        criteria: [
          {
            version: 1,
            id: 'criterion-1',
            description: 'Contract tests pass',
            required: true,
          },
        ],
        created_at: timestamp,
        updated_at: timestamp,
      }),
    ).toBeDefined();
  });
});

describe('generation contracts', () => {
  it('exports every locked generation state', () => {
    expect(GenerationStateSchema.options).toEqual([
      'planning',
      'running',
      'pausing',
      'paused',
      'stopping',
      'stopped',
      'validating',
      'repairing',
      'completed',
      'failed',
    ]);
  });

  it('validates a nested typed GenerationEvent payload', () => {
    expect(GenerationEventSchema.parse(generationEvent(1))).toEqual(
      generationEvent(1),
    );
  });

  it('supports every required typed event family', () => {
    expect(EventFamilySchema.options).toEqual([
      'generation',
      'plan',
      'focus',
      'frame',
      'section',
      'component',
      'style',
      'asset',
      'transaction',
      'validation',
      'repair',
      'preview',
      'state',
    ]);

    const payloads = [
      { version: 1, family: 'generation', run_id: 'run-1', state: 'running' },
      { version: 1, family: 'plan', plan_id: 'plan-1', action: 'updated' },
      { version: 1, family: 'focus', focus_lock_id: 'focus-1', action: 'acquired' },
      { version: 1, family: 'frame', frame_id: 'frame-1', action: 'updated' },
      { version: 1, family: 'section', section_id: 'section-1', action: 'updated' },
      { version: 1, family: 'component', component_id: 'component-1', action: 'updated' },
      { version: 1, family: 'style', target_id: 'component-1', action: 'updated' },
      { version: 1, family: 'asset', asset_id: 'asset-1', action: 'created' },
      { version: 1, family: 'transaction', transaction_id: 'transaction-1', state: 'open' },
      { version: 1, family: 'validation', validation_result_id: 'validation-1', outcome: 'pass' },
      { version: 1, family: 'repair', repair_run_id: 'repair-1', state: 'running' },
      { version: 1, family: 'preview', preview_id: 'preview-1', state: 'ready' },
      { version: 1, family: 'state', state: 'running', previous_state: 'planning' },
    ];

    for (const payload of payloads) {
      expect(GenerationEventPayloadSchema.safeParse(payload).success).toBe(true);
    }
  });

  it('rejects an unsupported contract version', () => {
    expect(
      GenerationEventSchema.safeParse({
        ...generationEvent(1),
        version: 2,
      }).success,
    ).toBe(false);
  });

  it('rejects a non-monotonic event sequence', () => {
    expect(() =>
      validateGenerationEventSequence([
        generationEvent(2),
        generationEvent(2),
      ]),
    ).toThrow(/monotonic/);
  });

  it('accepts locked steering controls and priorities', () => {
    const event = {
      version: 1,
      id: 'steering-1',
      project_id: 'project-1',
      generation_run_id: 'run-1',
      control: 'pause',
      priority: 'safe_point',
      instruction: null,
      created_at: timestamp,
    };

    expect(SteeringEventSchema.parse(event)).toEqual(event);
  });

  it('validates GenerationRun and RenderTransaction state', () => {
    expect(
      GenerationRunSchema.parse({
        version: 1,
        id: 'run-1',
        project_id: 'project-1',
        task_id: 'task-1',
        state: 'running',
        revision: '1',
        base_revision: '0',
        started_at: timestamp,
        ended_at: null,
      }),
    ).toBeDefined();
    expect(
      RenderTransactionSchema.parse({
        version: 1,
        id: 'transaction-1',
        project_id: 'project-1',
        generation_run_id: 'run-1',
        state: 'validating',
        revision: '1',
        base_revision: '0',
        candidate_revision: 'git-candidate-1',
        last_known_good_revision: 'git-good-1',
        created_at: timestamp,
        updated_at: timestamp,
      }),
    ).toBeDefined();
  });
});
