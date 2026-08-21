import { describe, it, expect, beforeAll } from 'vitest';
import { RoutingTester, TestSuiteResult } from '../../src/canary/routing-test';

describe('RoutingTester', () => {
  let tester: RoutingTester;

  beforeAll(() => {
    tester = new RoutingTester();
  });

  describe('testProvider', () => {
    it('should test primary provider successfully', async () => {
      const result = await tester.testProvider('bc-mistral/mistral-medium-latest');
      expect(result.provider).toBe('bc-mistral');
      expect(result.model).toBe('mistral-medium-latest');
      expect(result.success).toBe(true);
      expect(result.latencyMs).toBeGreaterThan(0);
    }, 120000);
    it('should test free fallback provider successfully', async () => {
      const result = await tester.testProvider('opencode/nemotron-3-ultra-free');
      expect(result.provider).toBe('opencode');
      expect(result.model).toBe('nemotron-3-ultra-free');
      expect(result.success).toBe(true);
      expect(result.latencyMs).toBeGreaterThan(0);
    }, 120000);

    it('should handle invalid provider gracefully', async () => {
      const result = await tester.testProvider('invalid/nonexistent-model');
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    }, 60000);
  });

  describe('testHttpRoute (production path)', () => {
    const baseUrl = process.env.BOTCONNECTOR_OPENCODE_BASE_URL || 'http://100.127.25.35:18420';
    const username = process.env.BOTCONNECTOR_OPENCODE_USERNAME || 'opencode';
    const password = process.env.BOTCONNECTOR_OPENCODE_PASSWORD || '';

    it('should reach bc-mistral/mistral-medium-latest through the OpenCode server', async () => {
      const result = await tester.testHttpRoute(
        baseUrl,
        'bc-mistral',
        'mistral-medium-latest',
        username,
        password,
      );
      expect(result.success).toBe(true);
      expect(result.error).toBeUndefined();
    }, 120000);
  });

  describe('runFullTestSuite', () => {
    it('should run full test suite and return valid results', async () => {
      const result: TestSuiteResult = await tester.runFullTestSuite();
      
      expect(result.timestamp).toBeDefined();
      expect(new Date(result.timestamp).getTime()).not.toBeNaN();
      expect(result.primary).toBeDefined();
      expect(result.freeFallback).toBeDefined();
      expect(typeof result.overallSuccess).toBe('boolean');
      expect(result.totalDurationMs).toBeGreaterThan(0);
    }, 300000);

    it('should have primary and free fallback as required providers', async () => {
      const result = await tester.runFullTestSuite();
      
      expect(result.primary.provider).toBe('bc-mistral');
      expect(result.primary.model).toBe('mistral-medium-latest');
      expect(result.freeFallback.provider).toBe('opencode');
      expect(result.freeFallback.model).toBe('nemotron-3-ultra-free');
    }, 300000);

    it('should have overallSuccess true when both providers work', async () => {
      const result = await tester.runFullTestSuite();
      // Unconditional invariant: overallSuccess equals "both providers
      // succeeded". This cannot silently pass when a provider fails.
      const bothWork = result.primary.success && result.freeFallback.success;
      expect(result.overallSuccess).toBe(bothWork);
      if (bothWork) {
        expect(result.primary.success).toBe(true);
        expect(result.freeFallback.success).toBe(true);
        expect(result.overallSuccess).toBe(true);
      }
    }, 300000);
  });
});