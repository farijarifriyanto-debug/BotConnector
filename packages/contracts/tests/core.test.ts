import { describe, expect, it } from 'vitest';

import {
  ArtifactManifestSchema,
  ProjectSchema,
} from '../src/index.js';

const project = {
  version: 1,
  id: 'project-1',
  name: 'Builder project',
  revision: '2',
  base_revision: '1',
  created_at: '2026-09-01T00:00:00.000Z',
  updated_at: '2026-09-01T00:00:00.000Z',
};

describe('core contracts', () => {
  it('accepts a valid Project root aggregate', () => {
    expect(ProjectSchema.parse(project)).toEqual(project);
  });

  it('rejects an invalid artifact type enum', () => {
    const result = ArtifactManifestSchema.safeParse({
      version: 1,
      id: 'artifact-1',
      project_id: project.id,
      type: 'database',
      lifecycle: 'draft',
      revision: '1',
      base_revision: '0',
      current_version_id: null,
      created_at: project.created_at,
      updated_at: project.updated_at,
    });

    expect(result.success).toBe(false);
  });

  it('rejects a Project missing a required property', () => {
    const { name: _name, ...withoutName } = project;
    expect(ProjectSchema.safeParse(withoutName).success).toBe(false);
  });

  it('rejects a base revision newer than the current revision', () => {
    expect(
      ProjectSchema.safeParse({
        ...project,
        revision: '1',
        base_revision: '2',
      }).success,
    ).toBe(false);
  });
});
