// Tests for DocToolsMenu.js. Run: node --test (in this directory). Each
// test loads the menu file with some of the real tool files, as Apps
// Script would, and checks the menu that onOpen() builds.
//
// SPDX-FileCopyrightText: David A. Wheeler and contributors
// SPDX-License-Identifier: MIT

'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const TOOLS = {
  mdToGdocs: 'MdToGdocs.js',
  linkify: 'linkifyCitations.js',
};

// Run onOpen() with the menu file and the named tools loaded; returns
// the menus added to the UI, as [name, [[caption, function name], ...]].
function menus(...tools) {
  const added = [];
  const ui = {
    createMenu(name) {
      const items = [];
      return {
        addItem(caption, fn) { items.push([caption, fn]); return this; },
        addToUi() { added.push([name, items]); },
      };
    },
  };
  const sandbox = { DocumentApp: { getUi: () => ui } };
  vm.createContext(sandbox);
  for (const f of [...tools.map(t => TOOLS[t]), 'DocToolsMenu.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), sandbox);
  }
  sandbox.onOpen();
  return added;
}

const SIDEBAR = ['Markdown changes sidebar', 'mdToGdocsShowSidebar'];
const LINKIFY = ['Linkify citations', 'linkifyCitations'];

test('all tools: one menu with every item', () => {
  assert.deepStrictEqual(menus('mdToGdocs', 'linkify'),
    [['Doc tools', [SIDEBAR, LINKIFY]]]);
});

test('one tool: only its item', () => {
  assert.deepStrictEqual(menus('mdToGdocs'), [['Doc tools', [SIDEBAR]]]);
  assert.deepStrictEqual(menus('linkify'), [['Doc tools', [LINKIFY]]]);
});

test('no tools: no menu', () => {
  assert.deepStrictEqual(menus(), []);
});

test('only the menu file defines onOpen()', () => {
  for (const f of Object.values(TOOLS)) {
    const src = fs.readFileSync(path.join(__dirname, f), 'utf8');
    assert.doesNotMatch(src, /function\s+onOpen\b/, f);
  }
});
