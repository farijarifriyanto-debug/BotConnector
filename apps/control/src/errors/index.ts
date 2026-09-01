export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'NOT_FOUND'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'REVISION_CONFLICT'
  | 'IDEMPOTENCY_CONFLICT'
  | 'DATABASE_UNAVAILABLE'
  | 'INTERNAL_ERROR'
  | 'INVALID_TASK_TRANSITION'
  | 'INVALID_GENERATION_RUN_TRANSITION'
  | 'FOCUS_LOCK_CONFLICT'
  | 'TASK_NOT_READY';

export class ControlApiError extends Error {
  constructor(
    public readonly code: ErrorCode,
    public readonly message: string,
    public readonly statusCode: number,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ControlApiError';
  }
}

export function validationError(message: string, details?: unknown): ControlApiError {
  return new ControlApiError('VALIDATION_ERROR', message, 422, details);
}

export function notFoundError(message: string): ControlApiError {
  return new ControlApiError('NOT_FOUND', message, 404);
}

export function unauthorizedError(message: string): ControlApiError {
  return new ControlApiError('UNAUTHORIZED', message, 401);
}

export function forbiddenError(message: string): ControlApiError {
  return new ControlApiError('FORBIDDEN', message, 403);
}

export function revisionConflictError(message: string): ControlApiError {
  return new ControlApiError('REVISION_CONFLICT', message, 409);
}

export function idempotencyConflictError(message: string): ControlApiError {
  return new ControlApiError('IDEMPOTENCY_CONFLICT', message, 409);
}

export function databaseUnavailableError(message: string): ControlApiError {
  return new ControlApiError('DATABASE_UNAVAILABLE', message, 503);
}

export function internalError(message: string): ControlApiError {
  return new ControlApiError('INTERNAL_ERROR', message, 500);
}

export function controlApiError(code: ErrorCode, message: string, statusCode: number, details?: unknown): ControlApiError {
  return new ControlApiError(code, message, statusCode, details);
}

export function isControlApiError(value: unknown): value is ControlApiError {
  return value instanceof ControlApiError;
}
