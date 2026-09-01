import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const ArtifactTypeSchema = z.enum([
  'web',
  'mobile',
  'design',
  'presentation',
  'document',
  'spreadsheet',
  'visualization',
  'animation',
]);

export const ArtifactLifecycleSchema = z.enum([
  'draft',
  'generating',
  'valid',
  'ready',
  'published',
  'archived',
]);

export const ProjectSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  name: z.string().min(1),
  ...revisionFields,
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const ArtifactManifestSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  type: ArtifactTypeSchema,
  lifecycle: ArtifactLifecycleSchema,
  ...revisionFields,
  current_version_id: IdentifierSchema.nullable(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const ArtifactVersionSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  artifact_id: IdentifierSchema,
  sequence: z.number().int().positive(),
  source_revision: IdentifierSchema,
  content_hash: z.string().min(1),
  created_at: TimestampSchema,
});

export const CheckpointSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  ...revisionFields,
  source_revision: IdentifierSchema,
  artifact_version_ids: z.array(IdentifierSchema),
  created_at: TimestampSchema,
});

export type Project = z.infer<typeof ProjectSchema>;
export type ArtifactManifest = z.infer<typeof ArtifactManifestSchema>;
export type ArtifactVersion = z.infer<typeof ArtifactVersionSchema>;
export type Checkpoint = z.infer<typeof CheckpointSchema>;
