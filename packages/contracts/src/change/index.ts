import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const ChangesetStateSchema = z.enum([
  'proposed',
  'approved',
  'applying',
  'applied',
  'rejected',
  'rolled_back',
]);

const workspaceRelativePathSchema = z.string().min(1).regex(
  /^(?!\/)(?![A-Za-z]:)(?!.*\\)(?!(?:.*\/)?\.\.(?:\/|$)).+$/,
  'Path must be workspace-relative and use POSIX separators',
);

const createFileOperationSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  kind: z.literal('create_file'),
  path: workspaceRelativePathSchema,
  content: z.string(),
});

const updateFileOperationSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  kind: z.literal('update_file'),
  path: workspaceRelativePathSchema,
  content: z.string(),
});

const deleteFileOperationSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  kind: z.literal('delete_file'),
  path: workspaceRelativePathSchema,
});

const moveFileOperationSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  kind: z.literal('move_file'),
  path: workspaceRelativePathSchema,
  destination_path: workspaceRelativePathSchema,
});

export const ChangeOperationSchema = z.discriminatedUnion('kind', [
  createFileOperationSchema,
  updateFileOperationSchema,
  deleteFileOperationSchema,
  moveFileOperationSchema,
]);

export const ChangesetSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  workspace_id: IdentifierSchema,
  state: ChangesetStateSchema,
  ...revisionFields,
  operations: z.array(ChangeOperationSchema).min(1),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export type ChangeOperation = z.infer<typeof ChangeOperationSchema>;
export type Changeset = z.infer<typeof ChangesetSchema>;
