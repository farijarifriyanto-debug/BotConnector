import {
  ProjectSchema,
  type Project,
} from '../../src/index.js';

export function parseFrontendProject(input: unknown): Project {
  return ProjectSchema.parse(input);
}
