import type { FastifyReply } from 'fastify';
import type { RequestContext } from '../request-context/index.js';
import type { ErrorCode } from '../errors/index.js';
import { isControlApiError } from '../errors/index.js';

export interface SuccessResponse<T = unknown> {
  data: T;
  meta: {
    request_id: string;
    revision?: string;
    next_cursor?: string;
  };
}

export interface ErrorResponse {
  error: {
    code: ErrorCode;
    message: string;
    request_id: string;
    details?: unknown;
  };
}

export function sendSuccess<T>(
  reply: FastifyReply,
  requestContext: RequestContext,
  data: T,
  options?: { revision?: string; nextCursor?: string; statusCode?: number },
): void {
  const meta: SuccessResponse['meta'] = {
    request_id: requestContext.requestId,
  };
  if (options?.revision !== undefined) {
    meta.revision = options.revision;
  }
  if (options?.nextCursor) {
    meta.next_cursor = options.nextCursor;
  }

  const response: SuccessResponse<T> = {
    data,
    meta,
  };

  reply.code(options?.statusCode ?? 200).send(response);
}

export function sendCreated<T>(
  reply: FastifyReply,
  requestContext: RequestContext,
  data: T,
  options?: { revision?: string },
): void {
  sendSuccess(reply, requestContext, data, {
    revision: options?.revision,
    statusCode: 201,
  });
}

export function sendNoContent(reply: FastifyReply): void {
  reply.code(204).send();
}

export function sendError(
  reply: FastifyReply,
  requestContext: RequestContext,
  error: unknown,
): void {
  if (isControlApiError(error)) {
    const response: ErrorResponse = {
      error: {
        code: error.code,
        message: error.message,
        request_id: requestContext.requestId,
        details: error.details,
      },
    };
    reply.code(error.statusCode).send(response);
    return;
  }

  const response: ErrorResponse = {
    error: {
      code: 'INTERNAL_ERROR',
      message: 'An unexpected error occurred',
      request_id: requestContext.requestId,
    },
  };
  reply.code(500).send(response);
}
