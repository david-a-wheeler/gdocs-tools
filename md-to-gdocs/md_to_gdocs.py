#!/usr/bin/env python3
"""Recreate Markdown edits in a Google Doc, as suggestions.

This is the local half of md-to-gdocs: it reads a git diff of a
Markdown file exported from a Google Doc, and works out each change
for the sidebar in the doc to apply: doc_paras() models the doc (the
paragraphs a Markdown file stands for, as the Google Doc has them),
and changes() turns a diff into changes to it.
"""

# SPDX-FileCopyrightText: OpenSSF project contributors
# SPDX-License-Identifier: MIT

import hashlib
import html
import json
import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt


@dataclass(frozen=True)
class Atom:
    """A word, a run of whitespace, or one other character, with its
    formatting. An image is an atom with no text."""
    text: str
    marks: frozenset = frozenset()  # any of "strong", "em", "code", "s"
    href: str | None = None
    image: str | None = None  # an image's alt text


@dataclass
class DocPara:
    """One paragraph of the Google Doc, as a Markdown file shows it.

    kind is "text" (an ordinary paragraph, including a block quote's,
    which starts with ">"), "empty", "heading", "list" (a list item),
    or "unsupported" (a table, code block, or horizontal rule, covering
    lines line to end)."""
    line: int  # 1-based line in the Markdown file
    kind: str
    atoms: tuple = ()
    level: int = 0  # a heading's level (1 to 6), or a list item's depth (0 = top)
    ordered: bool = False  # a numbered list item
    end: int = 0  # last line; the same as line except for "unsupported"

    @property
    def text(self):
        """The paragraph's plain text, as the doc shows it."""
        return ''.join(a.text for a in self.atoms)


_ATOM_RE = re.compile(r'\w+|\s+|[^\w\s]')
_TOC_RE = re.compile(r'\[[^\]]+\]\(#(?:\\.|[^)])*\)\s*$')
_HEADING_ID_RE = re.compile(r'[ \t]*\{#[^}]*\}')
_COMMENT_RE = re.compile(r'<!--.*-->\s*$')
_IMAGE_ATTRS_RE = re.compile(r'\{[^}]*\}')
_QUOTE_RE = re.compile(r' {0,3}>( ?)')
_MARKS = {'strong': 'strong', 'em': 'em', 's': 's'}

_md = MarkdownIt('commonmark', {'html': False, 'typographer': False})
_md.enable(['table', 'strikethrough'])


def _atoms(text, marks=frozenset(), href=None):
    return [Atom(t, marks, href) for t in _ATOM_RE.findall(text)]


def _filter_lines(lines):
    """Drop what isn't in the doc: whole-line HTML comments (cleanup's
    markdownlint directives) and Google's flat table of contents (a run
    of "[Text](#anchor)" lines, with blank lines between, before the
    second H1). Also strip heading IDs ("{#id}") from headings. These
    are cleanup-markdown's rules, so a raw export works too. Returns
    (original 1-based line number, text) pairs."""
    out = []
    h1_seen = 0
    in_toc = False
    for n, line in enumerate(lines, 1):
        if re.match(r'#[^#]', line):
            h1_seen += 1
        if _COMMENT_RE.match(line):
            continue
        if h1_seen < 2 and _TOC_RE.match(line):
            in_toc = True
            continue
        if in_toc and not line.strip():
            continue
        in_toc = False
        if line.startswith('#'):
            line = _HEADING_ID_RE.sub('', line)
        out.append((n, line))
    return out


def _inline_lines(children):
    """Split an inline token's children at line breaks: returns one
    list of atoms per source line."""
    lines = [[]]
    marks = set()
    hrefs = []
    after_image = False
    for t in children:
        if t.type in ('softbreak', 'hardbreak'):
            lines.append([])
        elif t.type.endswith('_open') and t.type[:-5] in _MARKS:
            marks.add(_MARKS[t.type[:-5]])
        elif t.type.endswith('_close') and t.type[:-6] in _MARKS:
            marks.discard(_MARKS[t.type[:-6]])
        elif t.type == 'link_open':
            hrefs.append(t.attrs.get('href'))
        elif t.type == 'link_close':
            hrefs.pop()
        elif t.type == 'code_inline':
            lines[-1] += _atoms(t.content, frozenset(marks | {'code'}),
                                hrefs[-1] if hrefs else None)
        elif t.type == 'image':
            lines[-1].append(Atom('', frozenset(marks),
                                  hrefs[-1] if hrefs else None, t.content))
            after_image = True
            continue
        elif t.type == 'text':
            text = t.content
            if after_image:
                # pandoc's image size ("{width=W height=H}"), from cleanup.
                text = _IMAGE_ATTRS_RE.sub('', text, count=1) \
                    if text.startswith('{') else text
            lines[-1] += _atoms(text, frozenset(marks),
                                hrefs[-1] if hrefs else None)
        after_image = False
    return lines


def doc_paras(markdown):
    """The Google Doc paragraphs that a Markdown file stands for, in
    order, as a list of DocPara.

    Each line of a Markdown paragraph is its own doc paragraph, however
    it ends ("\\", two spaces, or nothing), since Google's export writes
    two adjacent paragraphs as consecutive lines. A blank line between
    two lines of ordinary text, or after a list and before text, is an
    empty paragraph; other blank lines are just Markdown syntax. (In
    one doc, that was right nearly everywhere; before a list or a
    heading, the doc sometimes has an empty paragraph that the export
    can't show, since Markdown needs the blank line anyway.)"""
    kept = _filter_lines(markdown.split('\n'))
    orig = [n for n, _ in kept]
    src = [line for _, line in kept]
    tokens = _md.parse('\n'.join(src))

    paras = []  # (index into src, DocPara)
    lists = []  # open lists: True if ordered
    quote = 0
    item_start = False  # the next paragraph starts a list item
    heading = 0
    skip_to = None  # skip tokens up to this closing type (tables)
    for t in tokens:
        if skip_to:
            if t.type == skip_to:
                skip_to = None
            continue
        if t.type in ('bullet_list_open', 'ordered_list_open'):
            lists.append(t.type == 'ordered_list_open')
        elif t.type in ('bullet_list_close', 'ordered_list_close'):
            lists.pop()
        elif t.type == 'list_item_open':
            item_start = True
        elif t.type == 'blockquote_open':
            quote += 1
        elif t.type == 'blockquote_close':
            quote -= 1
        elif t.type == 'heading_open':
            heading = int(t.tag[1:])
        elif t.type in ('table_open', 'fence', 'code_block', 'hr'):
            first, last = t.map[0], t.map[1] - 1
            paras.append((first, DocPara(orig[first], 'unsupported',
                                         end=orig[last])))
            if t.type == 'table_open':
                skip_to = 'table_close'
        elif t.type == 'inline':
            for k, atoms in enumerate(_inline_lines(t.children)):
                i = t.map[0] + k
                if heading:
                    p = DocPara(orig[i], 'heading', tuple(atoms), heading)
                elif lists and item_start and k == 0:
                    p = DocPara(orig[i], 'list', tuple(atoms),
                                len(lists) - 1, lists[-1])
                else:
                    m = _QUOTE_RE.match(src[i]) if quote else None
                    if m:
                        atoms = _atoms('>' + m.group(1)) + atoms
                    p = DocPara(orig[i], 'text', tuple(atoms))
                p.end = p.line
                paras.append((i, p))
            heading = 0
            item_start = False

    result = []
    for k, (i, p) in enumerate(paras):
        if k and p.kind == 'text' and paras[k - 1][1].kind in ('text', 'list'):
            for j in range(paras[k - 1][0] + 1, i):
                if not src[j].strip():
                    result.append(DocPara(orig[j], 'empty', end=orig[j]))
        if p.end == 0:
            p.end = p.line
        result.append(p)
    return result


class DiffError(Exception):
    """The diff isn't one the tool can use."""


def parse_diff(diff):
    """Rebuild a file's old and new versions from a full-context unified
    diff (git diff -U100000) of that one file. Returns (old text, new
    text, old line -> new line for each unchanged line, changed old line
    numbers, changed new line numbers), with 1-based line numbers."""
    lines = diff.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    if sum(line.startswith('diff --git ') for line in lines) > 1:
        raise DiffError('the diff covers more than one file; give it one file')
    hunks = [i for i, line in enumerate(lines) if line.startswith('@@')]
    if not hunks:
        raise DiffError('the diff has no changes')
    m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', lines[hunks[0]])
    if len(hunks) > 1 or not m or int(m.group(1)) > 1 or int(m.group(2)) > 1:
        raise DiffError('the diff needs the whole file as context; '
                        'rerun git diff with -U100000')
    old, new = [], []
    line_map, old_changed, new_changed = {}, set(), set()
    old_eol = new_eol = True
    prev = ''
    for line in lines[hunks[0] + 1:]:
        tag, text = line[:1], line[1:]
        if tag == ' ':
            old.append(text)
            new.append(text)
            line_map[len(old)] = len(new)
        elif tag == '-':
            old.append(text)
            old_changed.add(len(old))
        elif tag == '+':
            new.append(text)
            new_changed.add(len(new))
        elif tag == '\\':  # "\ No newline at end of file", for the line before
            if prev == '-':
                old_eol = False
            elif prev == '+':
                new_eol = False
            else:
                old_eol = new_eol = False
        else:
            raise DiffError('unexpected line in the diff: ' + line[:60])
        prev = tag
    return ('\n'.join(old) + ('\n' if old and old_eol else ''),
            '\n'.join(new) + ('\n' if new and new_eol else ''),
            line_map, old_changed, new_changed)


@dataclass(frozen=True)
class Break:
    """A paragraph break, in a stream of atoms. It records the paragraph
    after it, so a change to that paragraph's kind is a change too."""
    kind: str
    level: int = 0
    ordered: bool = False


@dataclass
class Change:
    """One change to the doc: replace the old text from start to end
    with the new content. start and end are (index into the old doc's
    doc_paras(), character offset in that paragraph's text); they're
    equal for an insertion. kind is "insert" (start == end), "within"
    (one paragraph), or "across" (more than one)."""
    kind: str
    start: tuple
    end: tuple
    old_text: str  # what's replaced, with "\n" between paragraphs
    new_html: str  # what to paste
    new_text: str  # the same as plain text
    old_lines: tuple  # (first, last) lines of the old file it touches
    new_lines: tuple  # the same, in the new file
    flags: list = field(default_factory=list)
    id: str = ''


def _locatable(p):
    """Can the doc find this paragraph by its text?"""
    return p.kind in ('text', 'list', 'heading') and p.text.strip() != ''


def _same(p, q):
    return (p.kind, p.atoms, p.level, p.ordered) == \
        (q.kind, q.atoms, q.level, q.ordered)


def _stream(paras):
    """The atoms of consecutive doc paragraphs, with a Break between
    each two, and where each token starts: (index into paras, character
    offset). Also returns the end position."""
    tokens, starts = [], []
    for k, p in enumerate(paras):
        if k:
            tokens.append(Break(p.kind, p.level, p.ordered))
            starts.append((k - 1, len(paras[k - 1].text)))
        off = 0
        for a in p.atoms:
            tokens.append(a)
            starts.append((k, off))
            off += len(a.text)
    return tokens, starts, (len(paras) - 1, len(paras[-1].text))


def _has_word(tokens):
    return any(isinstance(t, Atom) and re.search(r'\w', t.text) for t in tokens)


def _inline_html(atoms, flags):
    out = []
    k = 0
    while k < len(atoms):
        a = atoms[k]
        n = k
        while n < len(atoms) and (atoms[n].marks, atoms[n].href) == (a.marks, a.href):
            n += 1
        text = html.escape(''.join(x.text for x in atoms[k:n]), quote=False)
        if any(x.image for x in atoms[k:n]):
            flags.add('image')
        for mark, tag in (('code', 'code'), ('s', 's'), ('em', 'i'), ('strong', 'b')):
            if mark in a.marks:
                text = f'<{tag}>{text}</{tag}>'
        if a.href and a.href.startswith('#'):
            flags.add('internal link')
        elif a.href:
            text = f'<a href="{html.escape(a.href)}">{text}</a>'
        out.append(text)
        k = n
    return ''.join(out)


_P = '<p style="margin-top:0;margin-bottom:0">'


def _render(lines, flags):
    """HTML for new content: lines are (kind, level, ordered, atoms),
    each but the last followed by a paragraph break. Pasted, <p>...</p>
    is the line and a break, a bare <br> is an empty line and a break,
    and the last line is bare, so it joins the text after the cursor
    (spike K6, K9, K10)."""
    out = []
    open_lists = []  # (tag, level)
    for k, (kind, level, ordered, atoms) in enumerate(lines):
        last = k == len(lines) - 1
        if kind != 'list' or last:
            while open_lists:
                out.append(f'</li></{open_lists.pop()[0]}>')
        inner = _inline_html(atoms, flags)
        if last:
            if kind == 'list':
                flags.add('list')
            out.append(inner)
        elif kind == 'list':
            flags.add('list')
            tag = 'ol' if ordered else 'ul'
            while open_lists and open_lists[-1][1] > level:
                out.append(f'</li></{open_lists.pop()[0]}>')
            if open_lists and open_lists[-1][1] == level:
                out.append('</li>')
            else:
                out.append(f'<{tag}>')
                open_lists.append((tag, level))
            out.append(f'<li style="margin-top:0;margin-bottom:0">{inner}')
        elif not ''.join(a.text for a in atoms) and not any(a.image for a in atoms):
            out.append('<br>')
        elif kind == 'heading':
            out.append(f'<h{level}>{inner}</h{level}>')
        else:
            out.append(f'{_P}{inner}</p>')
    return ''.join(out)


def _lines(tokens, first):
    """Split a stream into lines at Breaks: (kind, level, ordered,
    atoms), with first describing the first line's paragraph."""
    lines = [list(first) + [[]]]
    for t in tokens:
        if isinstance(t, Break):
            lines.append([t.kind, t.level, t.ordered, []])
        else:
            lines[-1][3].append(t)
    return [tuple(line) for line in lines]


def _change(old, new, oi, nj, old_paras, new_paras):
    """The change between two runs of doc paragraphs, old_paras (from
    old[oi]) and new_paras (from new[nj]), which start and end with the
    same unchanged paragraphs when there are any. Returns (the change,
    whether the doc can find where it goes), or None if nothing in the
    doc changes."""
    ot, ostarts, oend = _stream(old_paras)
    nt, nstarts, nend = _stream(new_paras)
    if ot == nt:
        return None
    # The unchanged paragraphs at each end mustn't be split, or a
    # paragraph that ends like it would take its place.
    head = len(old_paras[0].atoms) if _same(old_paras[0], new_paras[0]) else 0
    tail = len(old_paras[-1].atoms) if _same(old_paras[-1], new_paras[-1]) else 0
    limit = min(len(ot), len(nt))
    # Trim the common suffix first, so an inserted paragraph goes at the
    # end of the paragraph before it (the tested way), then the prefix.
    suffix = 0
    while suffix < limit - head and ot[-1 - suffix] == nt[-1 - suffix]:
        suffix += 1
    prefix = 0
    while prefix < limit - suffix and ot[prefix] == nt[prefix]:
        prefix += 1
    # Don't keep a common part that's only spaces and punctuation (a
    # trailing "." would otherwise move to an inserted paragraph): cut
    # back to a paragraph break, or to the unchanged paragraph.
    if prefix > head and not _has_word(ot[head:prefix]):
        breaks = [k for k in range(head, prefix) if isinstance(ot[k], Break)]
        prefix = breaks[-1] + 1 if breaks else head
    if suffix > tail and not _has_word(ot[len(ot) - suffix:len(ot) - tail]):
        breaks = [k for k in range(len(ot) - suffix, len(ot) - tail)
                  if isinstance(ot[k], Break)]
        suffix = len(ot) - breaks[0] if breaks else tail
    # Don't split a link.
    def in_link(tokens, k):
        return 0 < k < len(tokens) and all(
            isinstance(t, Atom) and t.href for t in (tokens[k - 1], tokens[k])) \
            and tokens[k - 1].href == tokens[k].href
    while prefix and (in_link(ot, prefix) or in_link(nt, prefix)):
        prefix -= 1
    while suffix and (in_link(ot, len(ot) - suffix) or in_link(nt, len(nt) - suffix)):
        suffix -= 1
    def pos(starts, end, k):
        return starts[k] if k < len(starts) else end

    # A pure insertion or deletion can often slide along the text it
    # repeats (e.g., a quiz added after another, where both end in
    # ENDQUIZ) with the same result. Choose the last place that's at
    # the end of a paragraph the doc can find: the tested way to insert
    # paragraphs, and the least surprising suggestion. A deletion
    # prefers to start at the start of one (normally the paragraph it
    # deletes), which keeps it off a neighbor that may change too.
    inserting = prefix == len(ot) - suffix
    if inserting != (prefix == len(nt) - suffix):
        mid = (nt if inserting else ot)[prefix:-suffix or None]
        rest = ot[len(ot) - suffix:]
        at_end = at_start = None
        for k in range(len(rest) + 1):
            here = pos(ostarts, oend, prefix + k)
            if _locatable(old_paras[here[0]]):
                if k == len(rest) or isinstance(rest[k], Break):
                    at_end = k
                elif here[1] == 0:
                    at_start = k
            if k == len(rest) or mid[k % len(mid)] != rest[k]:
                break
        best = at_end if inserting or at_start is None else at_start
        if best:
            prefix += best
            suffix -= best
    # The doc finds a place by the text around it, so don't start or end
    # in an empty paragraph: widen to the paragraph break before or after.
    while prefix and not old_paras[pos(ostarts, oend, prefix)[0]].text:
        prefix -= 1
    while suffix and not old_paras[pos(ostarts, oend, len(ot) - suffix)[0]].text:
        suffix -= 1

    start = pos(ostarts, oend, prefix)
    end = pos(ostarts, oend, len(ot) - suffix)
    nstart = pos(nstarts, nend, prefix)
    nfinish = pos(nstarts, nend, len(nt) - suffix)
    omid, nmid = ot[prefix:len(ot) - suffix], nt[prefix:len(nt) - suffix]

    flags = set()
    first = new_paras[nstart[0]]
    lines = _lines(nmid, (first.kind, first.level, first.ordered))
    new_html = _render(lines, flags) if nmid else ''
    new_text = '\n'.join(''.join(a.text for a in line[3]) for line in lines) \
        if nmid else ''
    old_text = ''.join('\n' if isinstance(t, Break) else t.text for t in omid)
    if any(isinstance(t, Atom) and t.image for t in omid):
        flags.add('image')
    if any(p.kind == 'unsupported' for p in old_paras + new_paras):
        flags.add('unsupported')
    # The first and last new lines join paragraphs already in the doc,
    # which keep their own style.
    if nmid and ((first.kind, first.level) !=
                 (old_paras[start[0]].kind, old_paras[start[0]].level) or
                 (new_paras[nfinish[0]].kind, new_paras[nfinish[0]].level) !=
                 (old_paras[end[0]].kind, old_paras[end[0]].level)):
        flags.add('style')
    kind = 'insert' if start == end else 'within' if start[0] == end[0] else 'across'
    # Where the doc can find it: by the text of a paragraph with text,
    # and for an insertion of paragraphs, only at the end of one.
    ok = _locatable(old_paras[start[0]]) and _locatable(old_paras[end[0]]) and \
        not (kind == 'insert' and nmid and isinstance(nmid[0], Break) and
             start[1] != len(old_paras[start[0]].text))
    s, e = (oi + start[0], start[1]), (oi + end[0], end[1])
    change = Change(kind, s, e, old_text, new_html, new_text,
                    (old[s[0]].line, old[e[0]].line),
                    (new[nj + nstart[0]].line, new[nj + nfinish[0]].line),
                    sorted(flags))
    context = [p.text for p in old_paras]
    change.id = hashlib.sha256(json.dumps(
        [context, start, end, old_text, new_html]).encode()).hexdigest()[:12]
    return change, ok


def _similar(a, b):
    """Is paragraph b paragraph a, edited? Yes if their common start and
    end cover at least half of the longer one."""
    if (a.kind, a.level) != (b.kind, b.level):
        return False
    x, y = a.text, b.text
    n = min(len(x), len(y))
    pre = 0
    while pre < n and x[pre] == y[pre]:
        pre += 1
    suf = 0
    while suf < n - pre and x[-1 - suf] == y[-1 - suf]:
        suf += 1
    return pre + suf >= max(len(x), len(y)) / 2


def changes(diff):
    """The changes a diff makes to the doc, last in the doc first (the
    order to apply them; see the design). Also returns the old doc's
    paragraphs, which the changes' positions refer to."""
    old_md, new_md, line_map, old_changed, new_changed = parse_diff(diff)
    old, new = doc_paras(old_md), doc_paras(new_md)

    # Paragraphs with text that git left unchanged, paired with their
    # new selves. (Empty paragraphs are left out: git pairs blank lines
    # freely, which can misalign the paragraphs around them.)
    new_at = {p.line: j for j, p in enumerate(new)}
    fixed = []
    for i, p in enumerate(old):
        if p.kind == 'empty' or any(n in old_changed for n in range(p.line, p.end + 1)):
            continue
        j = new_at.get(line_map.get(p.line))
        if j is None or (fixed and j <= fixed[-1][1]):
            continue
        if _same(p, new[j]) and line_map.get(p.end) == new[j].end:
            fixed.append((i, j))

    # Between those, pair each changed paragraph with the next new one
    # that's the same paragraph edited, so each edit stays a small change
    # within its paragraph, and what's left between pairs is paragraphs
    # inserted or deleted. Pairs are listed with whether they're edited.
    pairs = []
    for (i1, j1), (i2, j2) in zip([(-1, -1)] + fixed, fixed + [(len(old), len(new))]):
        j = j1 + 1
        for i in range(i1 + 1, i2):
            if old[i].kind == 'empty':
                continue
            for k in range(j, j2):
                if _similar(old[i], new[k]):
                    pairs.append((i, k, True))
                    j = k + 1
                    break
        if i2 < len(old):
            pairs.append((i2, j2, False))

    result = []
    for i, j, edited in pairs:
        if edited:
            c = _change(old, new, i, j, [old[i]], [new[j]])
            if c:
                result.append(c[0])
    # Between consecutive pairs: paragraphs inserted or deleted. Edited
    # paragraphs serve as context in their old form; their own edits
    # are separate changes.
    for (i1, j1, _), (i2, j2, _) in zip([(-1, -1, False)] + pairs,
                                        pairs + [(len(old), len(new), False)]):
        if i2 - i1 == 1 and j2 - j1 == 1:
            continue
        lo, hi = max(i1, 0), min(i2, len(old) - 1)
        ctx_old = old[lo:hi + 1]
        ctx_new = ([old[i1]] if i1 >= 0 else []) + new[j1 + 1:j2] + \
            ([old[i2]] if i2 < len(old) else [])
        c = _change(old, new, lo, max(j1, 0), ctx_old, ctx_new)
        if c:
            if not c[1]:
                c[0].flags.append('not found')
            result.append(c[0])
    result.sort(key=lambda c: (c.start, c.end), reverse=True)
    return old, result
