import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
  type JsonValue,
} from '../common.js';

export const UIIRNodeKindSchema = z.enum([
  'page',
  'section',
  'container',
  'heading',
  'text',
  'image',
  'icon',
  'button',
  'input',
  'list',
  'card',
  'navigation',
  'custom',
]);

const safeDeclarativeKeySchema = z
  .string()
  .min(1)
  .regex(
    /^[a-z][a-z0-9_-]*$/,
    'Declarative keys must use lowercase portable identifiers',
  )
  .regex(
    /^(?!on(?:abort|animation(?:end|iteration|start)?|auxclick|beforeinput|blur|cancel|canplay|change|click|close|contextmenu|copy|cut|dblclick|drag(?:end|enter|leave|over|start)?|drop|ended|error|focus|input|invalid|key(?:down|press|up)|load|message|mouse(?:down|enter|leave|move|out|over|up)|paste|pause|play|pointer(?:cancel|down|enter|leave|move|out|over|up)|reset|resize|scroll|submit|touch(?:cancel|end|move|start)|transitionend|unload|wheel)$).+$/,
    'Executable event-handler keys are forbidden',
  )
  .regex(
    /^(?!.*(?:api[-_]?key|access[-_]?token|auth[-_]?token|bearer[-_]?token|client[-_]?secret|private[-_]?key|provider[-_]?credentials?|refresh[-_]?token|password|passwd|secret|credential)).+$/,
    'Secret-bearing keys are forbidden',
  )
  .regex(
    /^(?!(?:.*[-_])?(?:command|eval|executable|javascript|script|shell|shell[-_]?command)(?:[-_].*)?$).+$/,
    'Executable keys are forbidden',
  );

const safeDeclarativeStringSchema = z
  .string()
  .regex(
    /^(?!\s*(?:[jJ][aA][vV][aA][sS][cC][rR][iI][pP][tT]|[vV][bB][sS][cC][rR][iI][pP][tT]):)/,
    'Executable URI schemes are forbidden',
  )
  .regex(
    /^(?!\s*[dD][aA][tT][aA]:[tT][eE][xX][tT]\/[hH][tT][mM][lL])/,
    'Executable data URIs are forbidden',
  )
  .regex(
    /^(?![\s\S]*[uU][rR][lL]\(\s*[jJ][aA][vV][aA][sS][cC][rR][iI][pP][tT]:)/,
    'Executable style URLs are forbidden',
  );

const safeDeclarativeValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.null(),
    z.boolean(),
    z.number(),
    safeDeclarativeStringSchema,
    z.array(safeDeclarativeValueSchema),
    z.record(safeDeclarativeKeySchema, safeDeclarativeValueSchema),
  ]),
);

const declarativeRecordSchema = z.record(
  safeDeclarativeKeySchema,
  safeDeclarativeValueSchema,
);

export const UIIRNodeSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  kind: UIIRNodeKindSchema,
  semantic_role: z.string().min(1).nullable(),
  content: z.string().nullable(),
  layout: declarativeRecordSchema,
  style: declarativeRecordSchema,
  tokens: declarativeRecordSchema,
  children: z.array(IdentifierSchema),
  bindings: declarativeRecordSchema,
  metadata: declarativeRecordSchema,
});

export const UIIRSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  artifact_id: IdentifierSchema,
  ...revisionFields,
  root_node_id: IdentifierSchema,
  nodes: z.array(UIIRNodeSchema).min(1),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
}).superRefine((value, context) => {
  const nodeIds = new Set<string>();
  for (const [index, node] of value.nodes.entries()) {
    if (nodeIds.has(node.id)) {
      context.addIssue({
        code: 'custom',
        path: ['nodes', index, 'id'],
        message: 'UI-IR node ids must be unique',
      });
    }
    nodeIds.add(node.id);
  }

  if (!nodeIds.has(value.root_node_id)) {
    context.addIssue({
      code: 'custom',
      path: ['root_node_id'],
      message: 'root_node_id must reference an existing node',
    });
  }

  for (const [nodeIndex, node] of value.nodes.entries()) {
    for (const [childIndex, childId] of node.children.entries()) {
      if (!nodeIds.has(childId)) {
        context.addIssue({
          code: 'custom',
          path: ['nodes', nodeIndex, 'children', childIndex],
          message: 'Child ids must reference existing nodes',
        });
      }
    }
  }

  const nodesById = new Map(value.nodes.map((node) => [node.id, node]));
  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (nodeId: string): void => {
    if (visiting.has(nodeId)) {
      context.addIssue({
        code: 'custom',
        path: ['nodes'],
        message: 'UI-IR child graph must be acyclic',
      });
      return;
    }
    if (visited.has(nodeId)) return;

    const node = nodesById.get(nodeId);
    if (!node) return;

    visiting.add(nodeId);
    for (const childId of node.children) visit(childId);
    visiting.delete(nodeId);
    visited.add(nodeId);
  };

  visit(value.root_node_id);
  for (const [index, node] of value.nodes.entries()) {
    if (!visited.has(node.id)) {
      context.addIssue({
        code: 'custom',
        path: ['nodes', index],
        message: 'Every UI-IR node must be reachable from root_node_id',
      });
    }
  }
});

export const SelectionContextSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  artifact_id: IdentifierSchema,
  uiir_revision: z.number().int().nonnegative(),
  selected_node_ids: z.array(IdentifierSchema).min(1),
  primary_node_id: IdentifierSchema.nullable(),
  created_at: TimestampSchema,
}).refine(
  (value) =>
    value.primary_node_id === null ||
    value.selected_node_ids.includes(value.primary_node_id),
  {
    path: ['primary_node_id'],
    message: 'primary_node_id must be one of selected_node_ids',
  },
);

export const DesignDecisionSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema.nullable(),
  summary: z.string().min(1),
  rationale: z.string().min(1),
  ...revisionFields,
  created_at: TimestampSchema,
});

const ProjectMemoryEntrySchema = z.strictObject({
  key: safeDeclarativeKeySchema,
  value: safeDeclarativeValueSchema,
});

export const ProjectMemoryRevisionSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  ...revisionFields,
  entries: z.array(ProjectMemoryEntrySchema),
  created_at: TimestampSchema,
});

export type UIIRNode = z.infer<typeof UIIRNodeSchema>;
export type UIIR = z.infer<typeof UIIRSchema>;
export type SelectionContext = z.infer<typeof SelectionContextSchema>;
export type DesignDecision = z.infer<typeof DesignDecisionSchema>;
export type ProjectMemoryRevision = z.infer<typeof ProjectMemoryRevisionSchema>;
