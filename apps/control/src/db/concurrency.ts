import { revisionConflictError } from '../errors/index.js';

export function parseIfMatch(header: string | undefined): string {
  if (!header) {
    throw revisionConflictError('If-Match header is required for this operation');
  }

  const trimmed = header.replace(/^"|"$/g, '');

  if (!/^[0-9]+$/.test(trimmed)) {
    throw revisionConflictError('If-Match header must contain a valid revision number');
  }

  return trimmed;
}

export function assertRevisionMatch(
  currentRevision: string,
  ifMatchRevision: string,
  resourceType: string,
): void {
  if (currentRevision !== ifMatchRevision) {
    throw revisionConflictError(
      `${resourceType} revision ${currentRevision} does not match If-Match revision ${ifMatchRevision}`,
    );
  }
}

export function incrementRevision(revision: string): string {
  return (BigInt(revision) + 1n).toString();
}
