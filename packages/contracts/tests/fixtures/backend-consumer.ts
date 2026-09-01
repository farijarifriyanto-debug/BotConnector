import {
  ProjectSchema,
  type Project,
} from '../../src/index.js';

export function parseBackendProject(input: unknown): Project {
  return ProjectSchema.parse(input);
}
