import assert from "node:assert/strict";
import test from "node:test";
import {
  calculatePoolPressure,
  createFairUseGuard,
  checkFairUse,
  recordUsage,
  resetFairUseGuard,
  shouldUseXkiroFreePool,
} from "../src/xkiro-pool.ts";

test("calculatePoolPressure returns NORMAL_POOL when usage is below 50%", () => {
  const usage = {
    tokensUsed: 100_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  assert.equal(calculatePoolPressure(usage), "NORMAL_POOL");
});

test("calculatePoolPressure returns POOL_PRESSURE when usage is between 50-80%", () => {
  const usage = {
    tokensUsed: 300_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  assert.equal(calculatePoolPressure(usage), "POOL_PRESSURE");
});

test("calculatePoolPressure returns POOL_CRITICAL when usage is between 80-100%", () => {
  const usage = {
    tokensUsed: 450_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  assert.equal(calculatePoolPressure(usage), "POOL_CRITICAL");
});

test("calculatePoolPressure returns POOL_EXHAUSTED when usage is 100% or more", () => {
  const usage = {
    tokensUsed: 500_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  assert.equal(calculatePoolPressure(usage), "POOL_EXHAUSTED");
});

test("createFairUseGuard creates guard with default values", () => {
  const guard = createFairUseGuard();
  assert.equal(guard.maxTokensPerUser, 100_000);
  assert.equal(guard.windowHours, 24);
  assert.ok(guard.currentUsage instanceof Map);
});

test("checkFairUse allows request within limit", () => {
  const guard = createFairUseGuard(100_000, 24);
  const result = checkFairUse(guard, "user1", 50_000);
  assert.equal(result.allowed, true);
});

test("checkFairUse denies request exceeding limit", () => {
  const guard = createFairUseGuard(100_000, 24);
  recordUsage(guard, "user1", 80_000);
  const result = checkFairUse(guard, "user1", 30_000);
  assert.equal(result.allowed, false);
  assert.ok(result.reason?.includes("FAIR_USE_LIMIT_EXCEEDED"));
});

test("recordUsage tracks cumulative usage per user", () => {
  const guard = createFairUseGuard();
  recordUsage(guard, "user1", 10_000);
  recordUsage(guard, "user1", 20_000);
  assert.equal(guard.currentUsage.get("user1"), 30_000);
});

test("resetFairUseGuard clears all usage", () => {
  const guard = createFairUseGuard();
  recordUsage(guard, "user1", 10_000);
  recordUsage(guard, "user2", 20_000);
  resetFairUseGuard(guard);
  assert.equal(guard.currentUsage.size, 0);
});

test("shouldUseXkiroFreePool returns false for paid users", () => {
  const usage = {
    tokensUsed: 100_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  const result = shouldUseXkiroFreePool(usage, "xkiro", true);
  assert.equal(result.useFreePool, false);
  assert.equal(result.reason, "PAID_USER_NOT_ELIGIBLE");
});

test("shouldUseXkiroFreePool returns false for non-xkiro providers", () => {
  const usage = {
    tokensUsed: 100_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  const result = shouldUseXkiroFreePool(usage, "deepinfra", false);
  assert.equal(result.useFreePool, false);
  assert.equal(result.reason, "NOT_XKIRO_PROVIDER");
});

test("shouldUseXkiroFreePool returns false when pool is exhausted", () => {
  const usage = {
    tokensUsed: 500_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  const result = shouldUseXkiroFreePool(usage, "xkiro", false);
  assert.equal(result.useFreePool, false);
  assert.equal(result.reason, "POOL_EXHAUSTED");
});

test("shouldUseXkiroFreePool returns false when pool is critical", () => {
  const usage = {
    tokensUsed: 450_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  const result = shouldUseXkiroFreePool(usage, "xkiro", false);
  assert.equal(result.useFreePool, false);
  assert.equal(result.reason, "POOL_CRITICAL");
});

test("shouldUseXkiroFreePool returns true when pool is normal", () => {
  const usage = {
    tokensUsed: 100_000,
    tokensLimit: 500_000,
    resetAt: new Date(),
    lastChecked: new Date(),
  };
  const result = shouldUseXkiroFreePool(usage, "xkiro", false);
  assert.equal(result.useFreePool, true);
  assert.equal(result.reason, "NORMAL_POOL_OPERATION");
});
