// Test-only endpoints. Production configuration remains fail-closed.
process.env.SANDBOX_MANAGER_URL ??= 'http://127.0.0.1:65535';
process.env.SANDBOX_MANAGER_SECRET ??= 'control-test-secret';
process.env.SANDBOX_PREVIEW_URL ??= 'http://127.0.0.1:65536';
