// Tests for MdToGdocs.js, with fake Google objects. Run: node --test
// (in this directory). Most tests are end to end: md_to_gdocs.py makes
// the change list from real Markdown edits, and a fake doc built from
// the same Markdown must give back exactly each change's old text.
//
// SPDX-FileCopyrightText: OpenSSF project contributors
// SPDX-License-Identifier: MIT

'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');

const T = {
  PARAGRAPH: 'PARAGRAPH', LIST_ITEM: 'LIST_ITEM', TEXT: 'TEXT',
  TABLE_OF_CONTENTS: 'TABLE_OF_CONTENTS', BODY_SECTION: 'BODY_SECTION',
};

class El {
  constructor(type, children = []) {
    this.type = type;
    this.children = children;
    this.parent = null;
    for (const c of children) c.parent = this;
  }
  getType() { return this.type; }
  getParent() { return this.parent; }
  getNumChildren() { return this.children.length; }
  getChild(i) { return this.children[i]; }
  getChildIndex(c) { return this.children.indexOf(c); }
  getText() { return this.children.map(c => c.getText()).join(''); }
}

class Text extends El {
  constructor(text) { super(T.TEXT); this.text = text; }
  getText() { return this.text; }
  asText() { return this; }
}

// A paragraph; pieces of text become separate Text children.
function para(...pieces) {
  return new El(T.PARAGRAPH, pieces.filter(p => p !== '').map(p => new Text(p)));
}

class Body extends El {
  constructor(children) { super(T.BODY_SECTION, children); }
  texts() {
    const out = [];
    const walk = e => e instanceof Text ? out.push(e) : e.children.forEach(walk);
    walk(this);
    return out;
  }
  // Like findText(): the next match after from (a range), in document
  // order, never across Text elements.
  findText(pattern, from) {
    const texts = this.texts();
    let i = from ? texts.indexOf(from.getElement()) : 0;
    let at = from ? from.getEndOffsetInclusive() + 1 : 0;
    for (; i < texts.length; i++, at = 0) {
      const re = new RegExp(pattern, 'g');
      re.lastIndex = at;
      const m = re.exec(texts[i].getText());
      if (m) {
        const el = texts[i];
        const s = m.index;
        const e = m.index + m[0].length - 1;
        return { getElement: () => el, getStartOffset: () => s, getEndOffsetInclusive: () => e };
      }
    }
    return null;
  }
}

function fakeDoc(children) {
  const body = new Body(children);
  const doc = {
    cursor: null, selection: null,
    getBody: () => body,
    getTabs: () => [{ getChildTabs: () => [] }],
    newPosition: (el, offset) => ({ el, offset }),
    setCursor(p) { this.cursor = p; },
    setSelection(r) { this.selection = r; },
    newRange() {
      const ops = [];
      const rb = {
        addElement: (el, s, e) => { ops.push(['element', el, s, e]); return rb; },
        addElementsBetween: (a, s, b, e) => { ops.push(['between', a, s, b, e]); return rb; },
        build: () => ({ ops }),
      };
      return rb;
    },
  };
  return doc;
}

function load(doc) {
  const props = {};
  const sandbox = {
    DocumentApp: { ElementType: T, getActiveDocument: () => doc },
    PropertiesService: {
      getDocumentProperties: () => ({
        getProperty: k => (k in props ? props[k] : null),
        setProperty: (k, v) => { props[k] = v; },
      }),
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'MdToGdocs.js'), 'utf8'), sandbox);
  return sandbox;
}

function paraOf(el) {
  while (el && el.getType() !== T.PARAGRAPH && el.getType() !== T.LIST_ITEM) el = el.getParent();
  return el;
}

// The selected text, with "\n" for each paragraph break it covers.
function selectedText(doc) {
  const body = doc.getBody();
  const top = el => { let e = paraOf(el) || el; while (e.getParent() !== body) e = e.getParent(); return e; };
  // Pieces of text, each with whether it's a whole paragraph (which
  // includes the paragraph's break).
  const segs = [];
  for (const op of doc.selection.ops) {
    if (op[0] === 'between') {
      const [, a, s, b, e] = op;
      const i1 = body.getChildIndex(top(a));
      const i2 = body.getChildIndex(top(b));
      const mids = [];
      for (let i = i1 + 1; i < i2; i++) mids.push(body.getChild(i).getText());
      segs.push([[a.getText().slice(s), ...mids, b.getText().slice(0, e + 1)].join('\n'), false]);
    } else if (op[2] === undefined) {
      segs.push([op[1].getText(), true]);
    } else {
      segs.push([op[1].getText().slice(op[2], op[3] + 1), false]);
    }
  }
  // Pieces from different paragraphs are separated by a break.
  let out = '';
  segs.forEach(([text, whole], k) => {
    if (k && !segs[k - 1][1]) out += '\n';
    out += text + (whole ? '\n' : '');
  });
  return out;
}

// Run md_to_gdocs.py on an edit: the old doc's paragraphs and the
// change list.
function changeList(oldMd, newMd) {
  const script = `
import difflib, json, sys
sys.path.insert(0, ${JSON.stringify(__dirname)})
from md_to_gdocs import change_list, doc_paras
d = json.load(sys.stdin)
diff = ''.join(difflib.unified_diff(d['old'].splitlines(True), d['new'].splitlines(True), 'a', 'b', n=100000))
paras = [{'kind': p.kind, 'text': p.text} for p in doc_paras(d['old'])]
json.dump({'paras': paras, 'list': change_list(diff)}, sys.stdout)
`;
  return JSON.parse(execFileSync('python3', ['-I', '-c', script],
    { input: JSON.stringify({ old: oldMd, new: newMd }) }));
}

// A fake doc of the old Markdown's paragraphs, with a table of contents
// (which repeats the headings) at the top. edit lets a test make the
// doc differ from the Markdown in ways that shouldn't matter.
function docFor(paras, edit = t => t) {
  const toc = new El(T.TABLE_OF_CONTENTS,
    paras.filter(p => p.kind === 'heading').map(p => para(p.text)));
  return fakeDoc([toc, ...paras.map(p => para(edit(p.text)))]);
}

// Locate each change of an edit in a fresh fake doc; check it selects
// exactly the old text (or puts the cursor at the right place).
function checkEdit(oldMd, newMd, edit) {
  const { paras, list } = changeList(oldMd, newMd);
  assert.ok(list.changes.length > 0);
  for (const change of list.changes) {
    assert.deepStrictEqual(change.flags, []);
    const doc = docFor(paras, edit);
    const gs = load(doc);
    const r = gs.mdToGdocsLocate(change);
    assert.ok(r.ok, r.message);
    if (change.kind === 'insert') {
      assert.strictEqual(doc.selection, null);
      const p = paraOf(doc.cursor.el);
      const base = p.children.indexOf(doc.cursor.el) >= 0
        ? p.children.slice(0, p.children.indexOf(doc.cursor.el)).reduce((n, c) => n + c.getText().length, 0) : 0;
      assert.ok(p.getText().length >= base + doc.cursor.offset);
      // The cursor sits right after the span's before-text.
      const re = new RegExp(`(${change.start.before})$`);
      assert.match(p.getText().slice(0, base + doc.cursor.offset), re);
    } else {
      assert.strictEqual(selectedText(doc), change.old_text);
    }
  }
  return list.changes;
}

const QUIZ = n => `QUIZ\\\nQ1. Question ${n}?\n\nA) a\\\nB) b\\\nC) c\\\nD) d\n\nAnswer: A\\\nENDQUIZ`;

test('replace a word within a paragraph', () => {
  checkEdit('# Title\n\nOne.\n\nThe quick brown fox.\n\nTwo.\n',
            '# Title\n\nOne.\n\nThe slow brown fox.\n\nTwo.\n');
});

test('insert a paragraph after a paragraph', () => {
  checkEdit('One.\n\nTwo.\n', 'One.\n\nNew.\n\nTwo.\n');
});

test('insert a quiz after a quiz, where ENDQUIZ repeats', () => {
  const old = `# A\n\nText.\n\n${QUIZ(1)}\n\nMore.\n\n${QUIZ(2)}\n\nEnd.\n`;
  const nu = old.replace(`${QUIZ(2)}\n`, `${QUIZ(2)}\\\n${QUIZ(3)}\n`);
  const [c] = checkEdit(old, nu);
  assert.ok(c.start.landmark);
});

test('delete a paragraph', () => {
  checkEdit('One.\n\nGone.\n\nTwo.\n', 'One.\n\nTwo.\n');
});

test('replace across paragraphs', () => {
  checkEdit('Keep this. Old end.\n\nOld start. Keep that.\n',
            'Keep this. New text. Keep that.\n');
});

test('change a heading, skipping the table of contents', () => {
  checkEdit('# Title\n\n## Old heading\n\nText.\n', '# Title\n\n## New heading\n\nText.\n');
});

test('the doc may differ from the Markdown in quotes and whitespace', () => {
  checkEdit('He said "the quick brown fox" today.\n',
            'He said "the slow brown fox" today.\n',
            t => t.replace(/"([^"]*)"/g, '“$1”').replace(/ /g, ' '));
});

test('a paragraph split into several Text elements', () => {
  // Offsets are the paragraph's; the selection is in the second element.
  const doc = fakeDoc([para('The quick ', 'brown fox.')]);
  const gs = load(doc);
  gs.mdToGdocsLocate({ start: { before: 'brown ', middle: 'fox', after: '\\.',
    para_start: false, para_end: true, landmark: null }, end: null });
  const [[, el, s, e]] = doc.selection.ops;
  assert.deepStrictEqual([el.getText(), s, e], ['brown fox.', 6, 8]);
});

test('ambiguous or missing text is an error, not a guess', () => {
  const doc = fakeDoc([para('Same text.'), para('Same text.')]);
  const gs = load(doc);
  const span = { before: '', middle: 'Same', after: '', para_start: false, para_end: false, landmark: null };
  let r = gs.mdToGdocsLocate({ start: span, end: null });
  assert.ok(!r.ok);
  assert.match(r.message, /2 times/);
  r = gs.mdToGdocsLocate({ start: { ...span, middle: 'Nope' }, end: null });
  assert.match(r.message, /isn’t in the doc/);
  assert.strictEqual(doc.selection, null);
});

test('one call finds, reports timings, and saves progress', () => {
  const doc = fakeDoc([para('Find me here.')]);
  const gs = load(doc);
  const span = { before: '', middle: 'me', after: '', para_start: false, para_end: false, landmark: null };
  const r = gs.mdToGdocsLocate({ start: span, end: null }, { completed: ['x'], current: 'y' });
  assert.ok(r.ok);
  assert.strictEqual(r.searches, 2);  // the match, then a search for another
  for (const k of ['open', 'search', 'total']) assert.strictEqual(typeof r[k], 'number');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(gs.mdToGdocsGetProgress())),
    { completed: ['x'], current: 'y' });
});

test('progress survives in document properties', () => {
  const gs = load(fakeDoc([para('x')]));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(gs.mdToGdocsGetProgress())),
    { completed: [], current: null });
  gs.mdToGdocsSetProgress({ completed: ['abc'], current: 'def' });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(gs.mdToGdocsGetProgress())),
    { completed: ['abc'], current: 'def' });
});
