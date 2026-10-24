// Tests for MdToGdocs.js, with fake Google objects. Run: node --test
// (in this directory). Most tests are end to end: md_to_gdocs.py makes
// the change list from real Markdown edits, and a fake doc built from
// the same Markdown must give back exactly each change's old text.
//
// SPDX-FileCopyrightText: David A. Wheeler and contributors
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
  getHeading() { return this.heading || 'NORMAL'; }
  getPositionedImages() { return this.positioned || []; }
  copy() {
    const c = new El(this.type, this.children.map(k => k.copy()));
    c.heading = this.heading;
    return c;
  }
  editAsText() { return this.children[0]; }
}

// Text, with each character's formatting (bold, italic, underline,
// strikethrough, link, font); an insertion takes the formatting of the
// character before it, as typing does.
const PLAIN = { bold: false, italic: false, underline: false, strike: false, link: null, font: null };
class Text extends El {
  constructor(text, fmt = {}) {
    super(T.TEXT);
    this.text = text;
    this.fmt = [...text].map(() => ({ ...PLAIN, ...fmt }));
  }
  getText() { return this.text; }
  asText() { return this; }
  copy() {
    const c = new Text(this.text);
    c.fmt = this.fmt.map(f => ({ ...f }));
    return c;
  }
  setText(s) {
    const f = this.fmt[0] || PLAIN;
    this.text = s;
    this.fmt = [...s].map(() => ({ ...f }));
    return this;
  }
  insertText(i, s) {
    const f = this.fmt[i - 1] || this.fmt[i] || PLAIN;
    this.text = this.text.slice(0, i) + s + this.text.slice(i);
    this.fmt.splice(i, 0, ...[...s].map(() => ({ ...f })));
    return this;
  }
  deleteText(s, e) {
    this.text = this.text.slice(0, s) + this.text.slice(e + 1);
    this.fmt.splice(s, e - s + 1);
    return this;
  }
  set_(k, s, e, v) { for (let i = s; i <= e; i++) this.fmt[i][k] = v; return this; }
  isBold(i) { return this.fmt[i].bold; }
  isItalic(i) { return this.fmt[i].italic; }
  isUnderline(i) { return this.fmt[i].underline; }
  isStrikethrough(i) { return this.fmt[i].strike; }
  getLinkUrl(i) { return this.fmt[i].link; }
  getFontFamily(i) { return this.fmt[i].font; }
  setBold(s, e, v) { return this.set_('bold', s, e, v); }
  setItalic(s, e, v) { return this.set_('italic', s, e, v); }
  setUnderline(s, e, v) { return this.set_('underline', s, e, v); }
  setStrikethrough(s, e, v) { return this.set_('strike', s, e, v); }
  setLinkUrl(s, e, v) { return this.set_('link', s, e, v); }
}

// A paragraph; pieces of text become separate Text children. A piece
// can be a Text, to give it formatting.
function para(...pieces) {
  return new El(T.PARAGRAPH, pieces.filter(p => p !== '')
    .map(p => (p instanceof Text ? p : new Text(p))));
}

class Body extends El {
  constructor(children) { super(T.BODY_SECTION, children); }
  insertParagraph(i, p) {
    this.children.splice(i, 0, p);
    p.parent = this;
    return p;
  }
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
    saveAndClose() {},
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
    DocumentApp: { ElementType: T, ParagraphHeading: { NORMAL: 'NORMAL' },
      getActiveDocument: () => doc },
    LockService: { getDocumentLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
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
  return fakeDoc([toc, ...paras.map(p => {
    const el = para(edit(p.text));
    if (p.kind === 'heading') el.heading = 'HEADING';
    return el;
  })]);
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

test('insert a paragraph right after a heading', () => {
  // At the start of the next paragraph, so it keeps that paragraph's style.
  const [c] = checkEdit('# H\n\nText.\n', '# H\n\nNew.\n\nText.\n');
  assert.ok(c.start.para_start);
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

// Apply plain changes; the result as plain JSON (arrays made in the
// sandbox aren't deepStrictEqual to arrays made here).
const apply = (gs, changes, budget = 10000) =>
  JSON.parse(JSON.stringify(gs.mdToGdocsApplyPlain(changes, budget)));

// The doc's paragraphs' text.
const texts = doc => doc.getBody().children
  .filter(c => c.getType() !== T.TABLE_OF_CONTENTS).map(c => c.getText());

// Each run of a Text with the same bold and italic, e.g., [['a ', ''],
// ['b', 'B'], ['c', 'BI']], for the doc's paragraphs that have any.
const runs = doc => doc.getBody().children.filter(p => p.children[0] instanceof Text).map(p => {
  const t = p.children[0];
  const out = [];
  [...t.getText()].forEach((ch, i) => {
    const f = (t.fmt[i].bold ? 'B' : '') + (t.fmt[i].italic ? 'I' : '');
    if (out.length && out[out.length - 1][1] === f) out[out.length - 1][0] += ch;
    else out.push([ch, f]);
  });
  return out;
}).filter(r => r.some(([, f]) => f));

// Directly apply all of an edit's changes to a fake doc of the old
// Markdown: the doc must then match the new Markdown, and a rerun must
// change nothing. Returns the doc.
function checkApply(oldMd, newMd) {
  const { paras, list } = changeList(oldMd, newMd);
  const doc = docFor(paras);
  const gs = load(doc);
  const r = apply(gs, list.changes);
  assert.deepStrictEqual(r.skipped, []);
  const want = changeList(newMd, oldMd).paras.map(p => p.text);
  assert.deepStrictEqual(texts(doc), want);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(gs.mdToGdocsGetProgress().completed)),
    list.changes.map(c => c.id));
  assert.deepStrictEqual(apply(gs, list.changes).applied, []);
  assert.deepStrictEqual(texts(doc), want);
  return doc;
}

test('directly apply changes within paragraphs, with bold and italics', () => {
  const doc = checkApply(
    '# Title\n\nThe quick brown fox.\n\nOne two three.\n\nAn old word here.\n\nSome text.\n',
    '# New title\n\nThe slow brown fox.\n\nOne two x < y & z three.\n\nAn word here.\n\n' +
    'Some **very *bold*** and *new* text.\n');
  assert.deepStrictEqual(runs(doc),
    [[['Some ', ''], ['very ', 'B'], ['bold', 'BI'], [' and ', ''], ['new', 'I'], [' text.', '']]]);
});

test('directly insert paragraphs, e.g., quiz feedback, found after a landmark', () => {
  // "Answer: A" repeats, so these are found after a landmark, and still
  // match after the insertion.
  const quiz = n => `QUIZ\\\nQ1. Question ${n}?\n\nA) a${n}\\\nB) b\\\nC) c\\\nD) d\n\nAnswer: A\n\nENDQUIZ`;
  const fb = n => `Answer: A\n\nFeedback:\n\nA) Correct ${n}.\\\nB) *Not* this.\\\nC) **No**.\\\nD) No.\\\n`;
  const old = `# Quizzes\n\n${quiz(1)}\n\nText.\n\n${quiz(2)}\n`;
  const nu = old.replace(/(QUIZ\\\nQ1\. Question (\d)[^]*?)Answer: A\n/g, (m, q, n) => q + fb(n));
  assert.ok(changeList(old, nu).list.changes.every(c => c.start.landmark));
  const doc = checkApply(old, nu);
  const b = [['B) ', ''], ['Not', 'I'], [' this.', '']];
  const c = [['C) ', ''], ['No', 'B'], ['.', '']];
  assert.deepStrictEqual(runs(doc), [b, c, b, c]);
});

test('directly insert paragraphs after a heading, at the next one’s start', () => {
  checkApply('# H\n\nText.\n', '# H\n\nNew one.\n\nNew two.\n\nText.\n');
});

test('what isn’t applied directly', () => {
  const { paras, list } = changeList(
    'Text with a word.\n\nKeep.\n\nOne.\n\nTwo.\n\nKeep this.\n\nThree four five.\n',
    'Text with a `word`.\n\nKeep.\n\nOne. Two.\n\nKeep this.\n\nThree.\n\nFive.\n');
  const doc = docFor(paras);
  const span = { before: '', middle: 'Same', after: '', para_start: false, para_end: false, landmark: null };
  const c = (html, text) => ({ id: html, start: span, end: null, flags: [], old_text: 'Same',
    new_text: text, new_html: html });
  doc.getBody().children.push(para('Same.'), para('Same.'));
  const r = apply(load(doc), [...list.changes, c('New', 'New'), c('<b>b</b>', 'c')]);
  assert.deepStrictEqual(r.applied, []);
  assert.deepStrictEqual(r.skipped.map(s => s.message).sort(), [
    'it changes paragraph breaks',
    'it has formatting other than bold and italics',
    'it replaces text with paragraphs',
    'its new HTML and new text don’t match',
    'the text is in the doc 2 times',
  ]);
  assert.deepStrictEqual(texts(doc), [...paras.map(p => p.text), 'Same.', 'Same.']);
});

test('directly applied text doesn’t pick up its neighbors’ formatting', () => {
  const span = (before, middle) => ({ before, middle, after: '', para_start: false, para_end: false, landmark: null });
  const change = (before, middle, nu) =>
    ({ id: nu, start: span(before, middle), end: null, flags: [], old_text: middle, new_text: nu, new_html: nu });
  // Replacing a link is refused: the old text's last character is a link.
  let t = new Text('see here now');
  t.setLinkUrl(4, 7, 'https://example.com');
  let r = apply(load(fakeDoc([para(t)])), [change('see ', 'here', 'there')]);
  assert.match(r.skipped[0].message, /formatted/);
  // Inserting after plain text gives plain text, even inside bold.
  t = new Text('a b c');
  t.setBold(0, 4, true).setBold(1, 2, false);
  r = apply(load(fakeDoc([para(t)])), [change('a ', '', 'new ')]);
  assert.strictEqual(t.getText(), 'a new b c');
  assert.deepStrictEqual(t.fmt.slice(2, 6).map(f => f.bold), [false, false, false, false]);
  // Replacing plain text right after code is fine: the new text takes
  // the old text's font. But inserting right after code is refused.
  t = new Text('x is');
  t.fmt[0].font = 'Roboto Mono';
  const doc = fakeDoc([para(t)]);
  r = apply(load(doc), [change('x', ' is', ' was'), change('x', '', ' really')]);
  assert.deepStrictEqual(r.applied, [' was']);
  assert.match(r.skipped[0].message, /formatted/);
  assert.deepStrictEqual([t.getText(), t.fmt.map(f => f.font)], ['x was', ['Roboto Mono', null, null, null, null]]);
});

test('new paragraphs copy their paragraph, except for its formatting', () => {
  const span = { before: 'End', middle: '', after: '', para_start: true, para_end: true, landmark: null };
  const c = { id: 'x', start: span, end: null, flags: [], old_text: '', new_text: '\nNew.', new_html: '<br>New.' };
  // The paragraph's font carries over; its bold doesn't.
  let t = new Text('End', { font: 'Arial' });
  t.setBold(1, 2, true);
  let doc = fakeDoc([para(t), para('After.')]);
  apply(load(doc), [c]);
  assert.deepStrictEqual(texts(doc), ['End', 'New.', 'After.']);
  const nt = doc.getBody().children[1].children[0];
  assert.deepStrictEqual(nt.fmt.map(f => [f.font, f.bold]), Array(4).fill(['Arial', false]));
  // A paragraph that starts with bold, a heading, or one with a floating
  // image (which a copy would duplicate) is refused.
  t = new Text('End');
  t.setBold(0, 0, true);
  const h = para('End');
  h.heading = 'HEADING';
  const img = para('End');
  img.positioned = [{}];
  for (const [p, why] of [[para(t), /formatted/], [h, /heading/], [img, /image/]]) {
    doc = fakeDoc([p]);
    assert.match(apply(load(doc), [c]).skipped[0].message, why);
    assert.deepStrictEqual(texts(doc), ['End']);
  }
});

test('directly apply reworded paragraphs, one change within each', () => {
  checkApply('Q?\n\nC) An agent needs no data, while a bot needs datasets\\\n' +
             'D) A bot can perceive it, while an agent can\'t\n\nEnd.\n',
             'Q?\n\nC) An agent is built *without* data, while a bot is trained on datasets\\\n' +
             'D) A bot can change it, while an agent can’t\n\nEnd.\n');
});

test('directly applying stops when its time is up, after at least one', () => {
  const doc = fakeDoc([para('aaa'), para('bbb')]);
  const c = (id, middle) => ({ id, start: { before: '', middle, after: '', para_start: true,
    para_end: true, landmark: null }, end: null, flags: [], old_text: middle, new_text: 'z', new_html: 'z' });
  assert.strictEqual(apply(load(doc), [c('1', 'aaa'), c('2', 'bbb')], 0).tried, 1);
  assert.deepStrictEqual(texts(doc), ['z', 'bbb']);
});
