import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import {
  exportJsonSchemaBundle,
  exportOpenApiDocument,
} from '../dist/index.js';

const outputDirectory = fileURLToPath(new URL('../schema/', import.meta.url));
await mkdir(outputDirectory, { recursive: true });

await Promise.all([
  writeFile(
    new URL('../schema/contracts.schema.json', import.meta.url),
    `${JSON.stringify(exportJsonSchemaBundle(), null, 2)}\n`,
  ),
  writeFile(
    new URL('../schema/openapi-components.json', import.meta.url),
    `${JSON.stringify(exportOpenApiDocument(), null, 2)}\n`,
  ),
]);
