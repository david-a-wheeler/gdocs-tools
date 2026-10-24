// md-to-gdocs: the Apps Script side. Paste this into the doc's Apps
// Script project (Extensions > Apps Script) as a file named MdToGdocs,
// next to MdToGdocsSidebar.html and the menu file, DocToolsMenu.js. It
// only finds text and sets your cursor or selection; the sidebar puts
// the new text on the clipboard, and you paste it. Everything else was
// worked out locally by md_to_gdocs.py.
//
// Every global name starts with "mdToGdocs", since all files in an Apps
// Script project share one namespace. The menu file has the project's
// onOpen(), which adds an item for mdToGdocsShowSidebar.
//
// SPDX-FileCopyrightText: David A. Wheeler and contributors
// SPDX-License-Identifier: MIT

/**
 * @OnlyCurrentDoc
 */

function mdToGdocsShowSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('MdToGdocsSidebar')
    .setTitle('Markdown changes');
  DocumentApp.getUi().showSidebar(html);
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
    return 'Text selected: press Ctrl+V.';
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
  return 'Text selected: press Ctrl+V.';
}

// Why a change can't be applied directly, or '' if it can: it must be
// plain text (paragraphs of ordinary text; bold and italics are fine)
// with no warnings, and it may add paragraph breaks only by inserting
// new paragraphs. (Its place is unique in the doc, as every change's
// is: its text is there exactly once, or, when it repeats, e.g.,
// "Answer: A", it's the first match after a paragraph that is.)
function mdToGdocsNotPlain_(c) {
  if (c.end || /\n/.test(c.old_text)) return 'it changes paragraph breaks';
  if (c.old_text && /\n/.test(c.new_text)) return 'it replaces text with paragraphs';
  if (c.flags.length) return 'it has warnings';
  if (/</.test(c.new_html.replace(/<\/?[bi]>|<p[^>]*>|<\/p>|<br>/g, ''))) {
    return 'it has formatting other than bold and italics';
  }
  return '';
}

// A plain change's new HTML as lines of runs, [text, bold, italic]:
// <p ...>...</p> and <br> each end a line, and the text is escaped by
// Python's html.escape().
function mdToGdocsLines_(html) {
  const lines = [[]];
  const on = { b: false, i: false };
  for (const [, close, tag, entity, text] of html.matchAll(/<(\/?)(\w+)[^>]*>|&(\w+);|([^<&]+)/g)) {
    if (tag in on) on[tag] = !close;
    else if (tag === 'br' || (tag && close)) lines.push([]);
    else if (!tag) lines[lines.length - 1].push([text || { amp: '&', lt: '<', gt: '>' }[entity], on.b, on.i]);
  }
  return lines;
}

function mdToGdocsText_(line) {
  return line.map(r => r[0]).join('');
}

// Does a character have formatting that new text shouldn't pick up?
// Code is in a monospace font.
function mdToGdocsFormatted_(t, i) {
  return t.isBold(i) || t.isItalic(i) || t.isUnderline(i) || t.isStrikethrough(i) ||
    !!t.getLinkUrl(i) || /mono|courier|consolas/i.test(t.getFontFamily(i) || '');
}

// Write a line at offset at in Text t (inserting it, unless it's already
// there), plain except for its own bold and italics.
function mdToGdocsWrite_(t, at, line, insert = true) {
  for (const [text, bold, italic] of line.filter(r => r[0])) {
    if (insert) t.insertText(at, text);
    const end = at + text.length - 1;
    t.setBold(at, end, bold).setItalic(at, end, italic).setUnderline(at, end, false)
      .setStrikethrough(at, end, false).setLinkUrl(at, end, null);
    at = end + 1;
  }
}

const MD_TO_GDOCS_FORMATTED = 'it’s in or next to formatted text (e.g., bold, a link, or code)';

// Apply a plain change directly (not as a suggestion).
function mdToGdocsApplyOne_(body, c, stats) {
  const why = mdToGdocsNotPlain_(c);
  if (why) throw new Error(why);
  const lines = mdToGdocsLines_(c.new_html);
  if (lines.map(mdToGdocsText_).join('\n') !== c.new_text) {
    throw new Error('its new HTML and new text don’t match');
  }
  const a = mdToGdocsFind_(body, c.start, stats);
  if (lines.length > 1) {
    mdToGdocsInsertParas_(body, a, lines);
    return;
  }
  // Within a paragraph. The new text goes in before the old text is
  // deleted, so the Text element never empties. Its formatting is set,
  // but check that the character it follows (the old text's last
  // character, if any) is plain, in case anything else carries over.
  const p = mdToGdocsParts_(a.para).find(p => a.start >= p.base && a.end <= p.base + p.len);
  if (!p) throw new Error('the text spans an image');
  const s = a.start - p.base;
  const e = a.end - p.base;
  const ref = e > s ? e - 1 : s > 0 ? s - 1 : p.len ? 0 : -1;
  if (ref >= 0 && mdToGdocsFormatted_(p.t, ref)) throw new Error(MD_TO_GDOCS_FORMATTED);
  mdToGdocsWrite_(p.t, e, lines[0]);
  if (e > s) p.t.deleteText(s, e - 1);
}

// Insert lines at the start or end of a paragraph, as a paste would:
// the first line joins the text before that point, the last joins the
// text after it, and the lines between become new paragraphs. Each new
// paragraph is a copy of this one (so it gets the same style, as when a
// paste splits a paragraph) with its text replaced. So the paragraph
// must be an ordinary paragraph of the body with just text, starting
// with plain text.
function mdToGdocsInsertParas_(body, a, lines) {
  const P = a.para;
  const T = DocumentApp.ElementType;
  if (P.getType() !== T.PARAGRAPH || P.getParent().getType() !== T.BODY_SECTION ||
      P.getHeading() !== DocumentApp.ParagraphHeading.NORMAL) {
    throw new Error('it’s next to a heading, list, table, or other special paragraph');
  }
  if (P.getNumChildren() !== 1 || P.getChild(0).getType() !== T.TEXT) {
    throw new Error('it’s next to an image or other non-text item');
  }
  const t = P.getChild(0).asText();
  const len = t.getText().length;
  if (!len || (a.start !== 0 && a.start !== len)) throw new Error('it would split a paragraph');
  const atEnd = a.start === len;
  // The line that joins this paragraph, and the new paragraphs, which
  // go after it or before it.
  const joins = atEnd ? lines[0] : lines[lines.length - 1];
  const paras = atEnd ? lines.slice(1) : lines.slice(0, -1);
  if (mdToGdocsFormatted_(t, 0) || (atEnd && joins.length && mdToGdocsFormatted_(t, len - 1))) {
    throw new Error(MD_TO_GDOCS_FORMATTED);
  }
  const i = body.getChildIndex(P);
  const at = atEnd ? i + 1 : i;
  // The paragraph still matches after an insertion at its end (or its
  // start, when the joining line is empty), so check that the new
  // paragraphs aren't there already, or a rerun would add them again.
  const was = atEnd ? at : i - paras.length;
  const text = t.getText();
  if ((atEnd ? text.endsWith(mdToGdocsText_(joins)) : text.startsWith(mdToGdocsText_(joins))) &&
      was >= 0 && was + paras.length <= body.getNumChildren() &&
      paras.every((line, k) => body.getChild(was + k).getText() === mdToGdocsText_(line))) {
    throw new Error('its new paragraphs are already there');
  }
  paras.forEach((line, k) => {
    const nt = P.copy();
    nt.editAsText().setText(mdToGdocsText_(line));
    mdToGdocsWrite_(nt.editAsText(), 0, line, false);
    body.insertParagraph(at + k, nt);
  });
  mdToGdocsWrite_(t, atEnd ? len : 0, joins);
}

// Called from the sidebar: apply plain changes (in order) directly, until
// they're done or budget ms have passed, and mark the applied ones
// completed in your saved progress. Returns { applied: [ids], skipped:
// [{ id, message }], tried (how many changes it got to) }; the sidebar
// calls again with the rest.
function mdToGdocsApplyPlain(changes, budget) {
  const t0 = Date.now();
  const stats = { calls: 0, ms: 0 };
  const result = { applied: [], skipped: [], tried: 0 };
  const body = mdToGdocsDoc_().getBody();
  for (const c of changes) {
    if (result.tried && Date.now() - t0 >= budget) break;
    result.tried++;
    try {
      mdToGdocsApplyOne_(body, c, stats);
      result.applied.push(c.id);
    } catch (e) {
      result.skipped.push({ id: c.id, message: e.message });
    }
  }
  if (result.applied.length) {
    const progress = mdToGdocsGetProgress();
    progress.completed = [...new Set([...progress.completed, ...result.applied])];
    mdToGdocsSetProgress(progress);
  }
  return result;
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
