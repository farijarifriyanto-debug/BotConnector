# Shared Contracts Kernel

`@botconnector/contracts` is the canonical executable contract package shared by
frontend, backend, workers, and transport consumers. Zod schemas are the only
hand-written contract definitions; TypeScript types are inferred from those
schemas, and JSON Schema/OpenAPI files are generated from the same values.

## Versioning

Every public contract carries `version: 1`. Phase 1 establishes only this
baseline and does not implement migrations. Mutation-aware contracts also carry
`revision` and `base_revision` for future optimistic concurrency handling.

## Schema Library

Zod 4 is the sole runtime schema library. It was selected because it provides
strict runtime validation, TypeScript inference, discriminated unions, and
deterministic JSON Schema Draft 2020-12 export without a second schema adapter.
The generated schemas are valid OpenAPI 3.1 schema components.

## Usage

```ts
import {
  ProjectSchema,
  type Project,
  validateWebSocketPayload,
} from '@botconnector/contracts';

const project: Project = ProjectSchema.parse(input);
const event = validateWebSocketPayload(message);
```

## Commands

- `npm run test:contracts` runs only Phase 1 contract tests.
- `npm run typecheck:contracts` typechecks the package and consumer fixtures.
- `npm run build:contracts` emits the package to the ignored `dist/` directory.
- `npm run schema:contracts` deterministically regenerates `schema/*.json`.

Generated schema files must not be edited by hand.
