import { randomUUID } from 'node:crypto';

export interface PrincipalContext {
  userId: string;
  workspaceId: string;
}

export interface RequestContext {
  requestId: string;
  principal: PrincipalContext;
  timestamp: string;
}

export function createRequestId(): string {
  return randomUUID();
}

export function createRequestContext(
  principal: PrincipalContext,
  requestId?: string,
): RequestContext {
  return {
    requestId: requestId || createRequestId(),
    principal,
    timestamp: new Date().toISOString(),
  };
}
