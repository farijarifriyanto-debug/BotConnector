import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const DeploymentSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  artifact_id: IdentifierSchema,
  artifact_version_id: IdentifierSchema,
  environment: z.string().min(1),
  state: z.enum(['planned', 'running', 'succeeded', 'failed', 'cancelled']),
  ...revisionFields,
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export type Deployment = z.infer<typeof DeploymentSchema>;
