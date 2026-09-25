import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("xKiro capacity monitor never serializes credentials or account identity", () => {
  const source = fs.readFileSync("scripts/xkiro-capacity-snapshot.mjs", "utf8");
  assert.equal(source.includes("body?.user"), false);
  assert.equal(source.includes("body?.wallet"), false);
  assert.match(source, /free_tokens/);
  assert.match(source, /provider-capacity-snapshot\.v1/);
  assert.match(source, /00:00 UTC/);
});
