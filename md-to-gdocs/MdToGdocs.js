// md-to-gdocs: the Apps Script side. Paste this into the doc's Apps
// Script project (Extensions > Apps Script) as a file named MdToGdocs,
// next to MdToGdocsSidebar.html. It only finds text and sets your cursor
// or selection; the sidebar puts the new text on the clipboard, and you
// paste it. Everything else was worked out locally by md_to_gdocs.py.
//
// Every global name starts with "mdToGdocs", since all files in an Apps
// Script project share one namespace.
//
// SPDX-FileCopyrightText: OpenSSF project contributors
// SPDX-License-Identifier: MIT

/**
 * @OnlyCurrentDoc
 */

function onOpen() {
  DocumentApp.getUi().createMenu('Markdown changes')
    .addItem('Open sidebar', 'mdToGdocsShowSidebar')
    .addToUi();
}

function mdToGdocsShowSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('MdToGdocsSidebar')
    .setTitle('Markdown changes');
  DocumentApp.getUi().showSidebar(html);
}

// Called when the sidebar opens, so Apps Script's slow first call
// (about 5 s) happens while you load the change list.
function mdToGdocsWarmUp() {
  mdToGdocsDoc_();
  return true;
}

// getBody() is the first tab's body, which may not be the tab you're
// looking at, so refuse docs with several tabs.
function mdToGdocsDoc_() {
  const doc = DocumentApp.getActiveDocument();
  const tabs = doc.getTabs();
  if (tabs.length !== 1 || tabs[0].getChildTabs().length) {
    throw new Error('this handles only docs with exactly one tab');
  }
  return doc;
}

// The paragraph (or list item) an element is in, or null.
function mdToGdocsPara_(el) {
  const T = DocumentApp.ElementType;
  for (let e = el; e; e = e.getParent()) {
    const type = e.getType();
    if (type === T.PARAGRAPH || type === T.LIST_ITEM) return e;
  }
  return null;
}

// Is an element in the table of contents? Its entries repeat the
// headings' text.
function mdToGdocsInToc_(el) {
  for (let e = el; e; e = e.getParent()) {
    if (e.getType() === DocumentApp.ElementType.TABLE_OF_CONTENTS) return true;
  }
  return false;
}

// A paragraph's text can be split across several Text children (e.g.,
// around an inline image), so map paragraph offsets onto them.
function mdToGdocsParts_(para) {
  const parts = [];
  let base = 0;
  for (let i = 0; i < para.getNumChildren(); i++) {
    const c = para.getChild(i);
    if (c.getType() !== DocumentApp.ElementType.TEXT) continue;
    const t = c.asText();
    const len = t.getText().length;
    parts.push({ t, index: i, base, len });
    base += len;
  }
  return parts;
}

// Find a span (see md_to_gdocs.py's find_span()): the paragraph where
// before + middle + after matches exactly once (or first after its
// landmark), skipping the table of contents. Returns { para, range,
// start, end }, with start and end the middle's offsets in the
// paragraph's text. findText() finds the paragraph quickly; running the
// same pattern as a JavaScript regex there gives the middle's offsets.
function mdToGdocsFind_(body, span, stats) {
  let from = null;
  if (span.landmark) from = mdToGdocsFind_(body, span.landmark, stats).range;
  const full = span.before + span.middle + span.after;
  const re = new RegExp(`(${span.before})(${span.middle})(${span.after})`, 'y');
  const hits = [];
  const find = after => {
    const t = Date.now();
    const r = body.findText(full, after);
    stats.calls++;
    stats.ms += Date.now() - t;
    return r;
  };
  for (let r = find(from); r; r = find(r)) {
    const el = r.getElement();
    const para = mdToGdocsPara_(el);
    if (!para || mdToGdocsInToc_(para)) continue;
    const part = mdToGdocsParts_(para).find(p => p.index === para.getChildIndex(el));
    const text = para.getText();
    re.lastIndex = part.base + r.getStartOffset();
    const m = re.exec(text);
    if (!m) continue;
    if (span.para_start && m.index !== 0) continue;
    if (span.para_end && m.index + m[0].length !== text.length) continue;
    const start = m.index + m[1].length;
    hits.push({ para, range: r, start, end: start + m[2].length });
    if (span.landmark) break;
  }
  if (hits.length !== 1) {
    throw new Error(hits.length ? `the text is in the doc ${hits.length} times`
      : 'the text isn’t in the doc (or has changed)');
  }
  return hits[0];
}

function mdToGdocsPosition_(doc, para, offset) {
  const p = mdToGdocsParts_(para).find(p => offset <= p.base + p.len);
  return p ? doc.newPosition(p.t, offset - p.base) : doc.newPosition(para, 0);
}

// Add text from offset from to to (exclusive) of a paragraph to a range.
function mdToGdocsAddText_(rb, para, from, to) {
  for (const p of mdToGdocsParts_(para)) {
    const lo = Math.max(from, p.base);
    const hi = Math.min(to, p.base + p.len);
    if (lo < hi) rb.addElement(p.t, lo - p.base, hi - 1 - p.base);
  }
}

// Called from the sidebar: find a change (as in the change list), put
// your cursor there (an insertion) or select its old text, and save
// your progress (passed along, so a click needs only one call to Apps
// Script; each call is a fresh start that reopens the doc). Returns {
// ok, message, and timings in ms: open (opening the doc), search (all
// findText() calls), searches (how many), total }.
function mdToGdocsLocate(change, progress) {
  const t0 = Date.now();
  const stats = { calls: 0, ms: 0 };
  const result = { ok: false, message: '', open: 0, search: 0, searches: 0, total: 0 };
  try {
    const doc = mdToGdocsDoc_();
    const body = doc.getBody();
    body.getNumChildren();  // so opening the doc is timed here
    result.open = Date.now() - t0;
    result.message = mdToGdocsSelect_(doc, body, change, stats);
    result.ok = true;
  } catch (e) {
    result.message = e.message;
  }
  if (progress) {
    try {
      mdToGdocsSetProgress(progress);
    } catch (e) {
      result.message += ` (Couldn’t save progress: ${e.message})`;
    }
  }
  result.search = stats.ms;
  result.searches = stats.calls;
  result.total = Date.now() - t0;
  return result;
}

function mdToGdocsSelect_(doc, body, change, stats) {
  const a = mdToGdocsFind_(body, change.start, stats);
  if (!change.end) {
    if (a.start === a.end) {
      doc.setCursor(mdToGdocsPosition_(doc, a.para, a.start));
      return 'Cursor placed: press Ctrl+V.';
    }
    const rb = doc.newRange();
    mdToGdocsAddText_(rb, a.para, a.start, a.end);
    doc.setSelection(rb.build());
    return 'Text selected: press Ctrl+V (or Delete).';
  }
  // Across paragraphs: from the start span's middle to the end span's.
  const b = mdToGdocsFind_(body, change.end, stats);
  const BODY = DocumentApp.ElementType.BODY_SECTION;
  if (a.para.getParent().getType() !== BODY || b.para.getParent().getType() !== BODY) {
    throw new Error('the text is in a table or other container; do it by hand');
  }
  const i1 = body.getChildIndex(a.para);
  const i2 = body.getChildIndex(b.para);
  if (i2 <= i1) throw new Error('the end of the text comes before its start');
  const rb = doc.newRange();
  const aParts = mdToGdocsParts_(a.para);
  const bParts = mdToGdocsParts_(b.para);
  const aPart = aParts.find(p => a.start >= p.base && a.start < p.base + p.len);
  const bPart = bParts.find(p => b.end > p.base && b.end <= p.base + p.len);
  if (aPart && bPart && aParts.length === 1 && bParts.length === 1) {
    // Starts and ends within text: the way spike step F3 tested.
    rb.addElementsBetween(aPart.t, a.start - aPart.base, bPart.t, b.end - 1 - bPart.base);
  } else {
    // Starts at a paragraph's end or ends at one's start: the text that
    // is there, plus the whole paragraphs between.
    mdToGdocsAddText_(rb, a.para, a.start, a.para.getText().length);
    for (let i = i1 + 1; i < i2; i++) rb.addElement(body.getChild(i));
    mdToGdocsAddText_(rb, b.para, 0, b.end);
  }
  doc.setSelection(rb.build());
  return 'Text selected: press Ctrl+V (or Delete).';
}

// Your progress through a change list ("Completed" marks and the
// current change), kept in the doc's script properties so it survives
// closing the sidebar. The sidebar passes only the current list's IDs.
const MD_TO_GDOCS_PROGRESS = 'mdToGdocsProgress';

function mdToGdocsGetProgress() {
  const v = PropertiesService.getDocumentProperties().getProperty(MD_TO_GDOCS_PROGRESS);
  return v ? JSON.parse(v) : { completed: [], current: null };
}

function mdToGdocsSetProgress(progress) {
  PropertiesService.getDocumentProperties()
    .setProperty(MD_TO_GDOCS_PROGRESS, JSON.stringify(progress));
  return true;
}
