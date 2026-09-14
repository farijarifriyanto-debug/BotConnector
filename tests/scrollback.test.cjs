'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const viewport = require('../tui/viewport.cjs');
const views = require('../tui/views.cjs');

function state() {
  return { input: '', mode: 'Act', model: { name: 'Model', locality: 'Local', backend: 'cpu' }, runtime: { nCtx: 4096 }, usedTokens: 0, workspace: 'workspace', project: 'workspace', settings: {} };
}

function session(count) {
  return { messages: Array.from({ length: count }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: `message-${i}` })) };
}

test('LONG_CHAT_SCROLL_UP/DOWN + CTRL_HOME/END', () => {
  const bottom = viewport.move({ atBottom: true, offset: 0 }, 'up', 200, 20);
  assert.equal(bottom.atBottom, false);
  assert.equal(bottom.offset, 180);
  assert.equal(viewport.move(bottom, 'home', 200, 20).offset, 0);
  const end = viewport.move(viewport.move(bottom, 'home', 200, 20), 'end', 200, 20);
  assert.deepEqual(end, { offset: 200, atBottom: true });
  assert.equal(viewport.move(end, 'down', 200, 20).offset, 200);
});

test('FIRST_MESSAGE_REACHABLE_100/500 + COMPOSER_ALWAYS_PINNED', () => {
  const oldRows = process.stdout.rows, oldCols = process.stdout.columns;
  try {
    for (const [cols, rows] of [[80, 24], [100, 30], [120, 35], [160, 45]]) {
      Object.defineProperty(process.stdout, 'rows', { value: rows, configurable: true });
      Object.defineProperty(process.stdout, 'columns', { value: cols, configurable: true });
      for (const count of [10, 100, 500]) {
      const frame = views.homeFrame(state(), session(count), [], '', { conversationViewport: { offset: 0, atBottom: false } });
      assert.match(frame.lines.join('\n'), /message-0/);
      if (count >= 100) assert.ok(frame.conversationMaxStart > 0);
      assert.match(frame.lines[frame.cursorRow - 1], /│/);
      assert.match(frame.lines.at(-1), /Context/);
      }
    }
  } finally {
    Object.defineProperty(process.stdout, 'rows', { value: oldRows, configurable: true });
    Object.defineProperty(process.stdout, 'columns', { value: oldCols, configurable: true });
  }
});

test('SCROLL_AT_BOTTOM_AUTOFOLLOW + SCROLL_UP_NO_FORCED_AUTOFOLLOW + NEW_OUTPUT_INDICATOR', () => {
  const oldRows = process.stdout.rows, oldCols = process.stdout.columns;
  try {
    Object.defineProperty(process.stdout, 'rows', { value: 24, configurable: true });
    Object.defineProperty(process.stdout, 'columns', { value: 80, configurable: true });
    const bottom = views.homeFrame(state(), session(4), [], '', { conversationViewport: { atBottom: true, offset: 0 } });
    const follow = views.homeFrame(state(), session(20), [], '', { conversationViewport: { atBottom: true, offset: 0 } });
    assert.ok(follow.conversationStart > bottom.conversationStart);
    const scrolled = views.homeFrame(state(), session(20), [], '', { conversationViewport: { atBottom: false, offset: 0, unseenOutputCount: 3 } });
    assert.equal(scrolled.conversationStart, 0);
    assert.match(scrolled.lines.join('\n'), /↓ 3 new lines/);
    const resumed = viewport.move({ atBottom: false, offset: 0 }, 'end', scrolled.conversationMaxStart, scrolled.availableBodyRows);
    assert.equal(resumed.atBottom, true);
  } finally {
    Object.defineProperty(process.stdout, 'rows', { value: oldRows, configurable: true });
    Object.defineProperty(process.stdout, 'columns', { value: oldCols, configurable: true });
  }
});

test('MOUSE_WHEEL_IF_SUPPORTED + POPUP_DOES_NOT_DESTROY_SCROLL_STATE', () => {
  assert.deepEqual(viewport.parseMouseWheel('\x1b[<64;12;8M\x1b[<65;12;8M'), ['up', 'down']);
  const before = { atBottom: false, offset: 12 };
  const after = viewport.move(before, 'down', 100, 20);
  assert.equal(after.offset, 32);
  assert.equal(viewport.move(after, 'end', 100, 20).atBottom, true);
});

test('RESIZE_AT_BOTTOM and RESIZE_WHILE_SCROLLED preserve logical position', () => {
  const atBottom = viewport.move({ atBottom: true, offset: 0 }, 'end', 400, 20);
  assert.equal(atBottom.offset, 400);
  const scrolled = { atBottom: false, offset: 42 };
  assert.equal(viewport.clampOffset(scrolled.offset, 500), 42);
  assert.equal(viewport.clampOffset(scrolled.offset, 30), 30);
});
