import { describe, expect, it } from 'vitest';

import {
  AgentRoleSchema,
  AgentRunCapabilitySchema,
  AgentRunSchema,
  CapabilitySchema,
  ChangeOperationSchema,
  ChangesetSchema,
  ContextSnapshotSchema,
  DesignDecisionSchema,
  ModelRouteSchema,
  ProjectMemoryRevisionSchema,
  SelectionContextSchema,
  UIIRSchema,
} from '../src/index.js';

const timestamp = '2026-09-01T00:00:00.000Z';

const uiir = {
  version: 1,
  id: 'uiir-1',
  project_id: 'project-1',
  artifact_id: 'artifact-1',
  revision: '2',
  base_revision: '1',
  root_node_id: 'page-1',
  nodes: [
    {
      version: 1,
      id: 'page-1',
      kind: 'page',
      semantic_role: 'document',
      content: null,
      layout: { display: 'grid' },
      style: { color: '#111111' },
      tokens: { spacing: 'space-4' },
      bindings: {},
      metadata: { label: 'Home' },
      children: ['heading-1'],
    },
    {
      version: 1,
      id: 'heading-1',
      kind: 'heading',
      semantic_role: 'heading',
      content: 'Build safely',
      layout: {},
      style: {},
      tokens: {},
      bindings: {},
      metadata: {},
      children: [],
    },
  ],
  created_at: timestamp,
  updated_at: timestamp,
};

describe('design contracts', () => {
  it('accepts declarative UI-IR with node references', () => {
    expect(UIIRSchema.parse(uiir)).toEqual(uiir);
  });

  it('rejects unknown executable UI-IR fields', () => {
    const unsafe = structuredClone(uiir);
    Object.assign(unsafe.nodes[0], { javascript: 'alert(1)' });
    expect(UIIRSchema.safeParse(unsafe).success).toBe(false);
  });

  it('rejects executable or secret-bearing UI-IR metadata', () => {
    const unsafe = structuredClone(uiir);
    Object.assign(unsafe.nodes[0].metadata, {
      shell_command: 'rm -rf /',
    });
    expect(UIIRSchema.safeParse(unsafe).success).toBe(false);
  });

  it('rejects event handlers, credential keys, and nested secrets in UI-IR', () => {
    for (const metadata of [
      { onClick: 'alert(1)' },
      { password: 'forbidden' },
      { nested: { access_token: 'forbidden' } },
    ]) {
      const unsafe = structuredClone(uiir);
      Object.assign(unsafe.nodes[0].metadata, metadata);
      expect(UIIRSchema.safeParse(unsafe).success).toBe(false);
    }
  });

  it('rejects credential key variants and executable URI variants', () => {
    const unsafeMetadata = [
      { apikey: 'forbidden' },
      { 'api-key': 'forbidden' },
      { 'access-token': 'forbidden' },
      { clientsecret: 'forbidden' },
      { 'private-key': 'forbidden' },
      { dbpassword: 'forbidden' },
      { href: 'vbscript:msgbox(1)' },
      { href: 'data:text/html,<script>alert(1)</script>' },
      { background: 'url(javascript:alert(1))' },
    ];

    for (const metadata of unsafeMetadata) {
      const unsafe = structuredClone(uiir);
      Object.assign(unsafe.nodes[0].metadata, metadata);
      expect(UIIRSchema.safeParse(unsafe).success).toBe(false);
    }
  });

  it('accepts benign declarative keys that begin with on', () => {
    const safe = structuredClone(uiir);
    Object.assign(safe.nodes[0].metadata, {
      onboarding: 'complete',
      online: true,
    });
    expect(UIIRSchema.safeParse(safe).success).toBe(true);
  });

  it('rejects invalid UI-IR graph references and duplicate node ids', () => {
    const missingRoot = { ...structuredClone(uiir), root_node_id: 'missing' };
    expect(UIIRSchema.safeParse(missingRoot).success).toBe(false);

    const danglingChild = structuredClone(uiir);
    danglingChild.nodes[0].children = ['missing'];
    expect(UIIRSchema.safeParse(danglingChild).success).toBe(false);

    const duplicate = structuredClone(uiir);
    duplicate.nodes[1].id = 'page-1';
    expect(UIIRSchema.safeParse(duplicate).success).toBe(false);
  });

  it('rejects cyclic and disconnected UI-IR graphs', () => {
    const cyclic = structuredClone(uiir);
    cyclic.nodes[1].children = ['page-1'];
    expect(UIIRSchema.safeParse(cyclic).success).toBe(false);

    const disconnected = structuredClone(uiir);
    disconnected.nodes[0].children = [];
    expect(UIIRSchema.safeParse(disconnected).success).toBe(false);
  });

  it('validates SelectionContext structure', () => {
    const selection = {
      version: 1,
      id: 'selection-1',
      project_id: 'project-1',
      artifact_id: 'artifact-1',
      uiir_revision: '2',
      selected_node_ids: ['heading-1'],
      primary_node_id: 'heading-1',
      created_at: timestamp,
    };
    expect(SelectionContextSchema.parse(selection)).toEqual(selection);

    expect(
      SelectionContextSchema.safeParse({
        ...selection,
        primary_node_id: 'not-selected',
      }).success,
    ).toBe(false);
  });

  it('validates design decisions and project memory revisions', () => {
    expect(
      DesignDecisionSchema.parse({
        version: 1,
        id: 'decision-1',
        project_id: 'project-1',
        task_id: 'task-1',
        summary: 'Use a flat UI-IR node graph',
        rationale: 'Stable references for selections',
        revision: '1',
        base_revision: '0',
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      ProjectMemoryRevisionSchema.parse({
        version: 1,
        id: 'memory-1',
        project_id: 'project-1',
        revision: '1',
        base_revision: '0',
        entries: [{ key: 'design-tone', value: 'precise' }],
        created_at: timestamp,
      }),
    ).toBeDefined();
  });

  it('rejects secret-bearing Project Memory keys', () => {
    const result = ProjectMemoryRevisionSchema.safeParse({
      version: 1,
      id: 'memory-1',
      project_id: 'project-1',
      revision: '1',
      base_revision: '0',
      entries: [{ key: 'provider_credentials', value: 'forbidden' }],
      created_at: timestamp,
    });
    expect(result.success).toBe(false);
  });

  it('rejects nested secret-bearing Project Memory values', () => {
    const result = ProjectMemoryRevisionSchema.safeParse({
      version: 1,
      id: 'memory-1',
      project_id: 'project-1',
      revision: '1',
      base_revision: '0',
      entries: [
        { key: 'provider', value: { nested: { access_token: 'forbidden' } } },
      ],
      created_at: timestamp,
    });
    expect(result.success).toBe(false);
  });
});

describe('AI contracts', () => {
  it('exports every locked agent role', () => {
    expect(AgentRoleSchema.options).toEqual([
      'planner',
      'designer',
      'coder',
      'researcher',
      'tester',
      'repairer',
      'merger',
    ]);
  });

  it('validates agent, context, route, and capability contracts', () => {
    expect(
      AgentRunSchema.parse({
        version: 1,
        id: 'agent-run-1',
        project_id: 'project-1',
        task_id: 'task-1',
        role: 'coder',
        state: 'running',
        context_snapshot_id: 'context-1',
        model_route_id: 'route-1',
        revision: '1',
        base_revision: '0',
        started_at: timestamp,
        ended_at: null,
      }),
    ).toBeDefined();
    expect(
      ContextSnapshotSchema.parse({
        version: 1,
        id: 'context-1',
        project_id: 'project-1',
        task_id: 'task-1',
        project_revision: '2',
        checkpoint_id: null,
        resource_refs: ['git:HEAD'],
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      ModelRouteSchema.parse({
        version: 1,
        id: 'route-1',
        project_id: 'project-1',
        selected_candidate_id: 'candidate-1',
        revision: '1',
        base_revision: '0',
        candidates: [
          {
            version: 1,
            id: 'candidate-1',
            provider: 'provider-name',
            model: 'model-name',
            priority: 1,
          },
        ],
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      CapabilitySchema.parse({
        version: 1,
        id: 'capability-1',
        domain: 'filesystem',
        effect: 'write',
        approval: 'policy',
      }),
    ).toBeDefined();
    expect(
      AgentRunCapabilitySchema.parse({
        version: 1,
        id: 'grant-1',
        agent_run_id: 'agent-run-1',
        capability_id: 'capability-1',
        granted: true,
        approval_reference: 'policy-1',
      }),
    ).toBeDefined();
  });
});

describe('change contracts', () => {
  it('validates each Changeset operation kind', () => {
    const operations = [
      { version: 1, id: 'op-1', kind: 'create_file', path: 'src/a.ts', content: 'a' },
      { version: 1, id: 'op-2', kind: 'update_file', path: 'src/a.ts', content: 'b' },
      { version: 1, id: 'op-3', kind: 'delete_file', path: 'src/a.ts' },
      { version: 1, id: 'op-4', kind: 'move_file', path: 'src/a.ts', destination_path: 'src/b.ts' },
    ];
    for (const operation of operations) {
      expect(ChangeOperationSchema.safeParse(operation).success).toBe(true);
    }
  });

  it('rejects path traversal and absolute Changeset paths', () => {
    for (const path of ['../../etc/passwd', '/etc/passwd', 'C:/Windows/system.ini']) {
      expect(
        ChangeOperationSchema.safeParse({
          version: 1,
          id: 'op-unsafe',
          kind: 'delete_file',
          path,
        }).success,
      ).toBe(false);
    }
  });

  it('validates a Changeset with optimistic concurrency fields', () => {
    const changeset = {
      version: 1,
      id: 'changeset-1',
      project_id: 'project-1',
      task_id: 'task-1',
      workspace_id: 'workspace-1',
      state: 'proposed',
      revision: '2',
      base_revision: '1',
      operations: [
        {
          version: 1,
          id: 'op-1',
          kind: 'update_file',
          path: 'src/a.ts',
          content: 'updated',
        },
      ],
      created_at: timestamp,
      updated_at: timestamp,
    };
    expect(ChangesetSchema.parse(changeset)).toEqual(changeset);
  });
});
