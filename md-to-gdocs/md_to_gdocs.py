#!/usr/bin/env python3
"""Recreate Markdown edits in a Google Doc, as suggestions.

This is the local half of md-to-gdocs: it reads a git diff of a
Markdown file exported from a Google Doc, and works out each change
for the sidebar in the doc to apply: doc_paras() models the doc (the
paragraphs a Markdown file stands for, as the Google Doc has them),
changes() turns a diff into changes to it, and change_list() adds how
to find each in the doc. Run as a command, it reads the diff on
standard input (or from a file) and writes the change list as JSON:

    git diff -U100000 BASE -- FILE.md | python3 -I md_to_gdocs.py > ,changes.json
"""

# SPDX-FileCopyrightText: OpenSSF project contributors
# SPDX-License-Identifier: MIT

import hashlib
import html
import json
import re
import sys
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
    # The unchanged paragraphs at the end (with the break before each).
    tail = n = 0
    while (n < min(len(old_paras), len(new_paras)) - 1 and
           _same(old_paras[-1 - n], new_paras[-1 - n])):
        tail += len(old_paras[-1 - n].atoms) + 1
        n += 1
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
            there = pos(ostarts, oend, prefix + k + (0 if inserting else len(mid)))
            if _locatable(old_paras[here[0]]) and _locatable(old_paras[there[0]]):
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

    # Docs drops whitespace at the edge of pasted HTML (and a no-break
    # space would be a different character), so if the new text starts
    # or ends with a space, widen the change by the word or punctuation
    # next to it: e.g., insert ", carefully" for "," rather than
    # " carefully" after it.
    def space(t):
        return isinstance(t, Atom) and t.text.isspace()
    while prefix < len(nt) - suffix:
        if space(nt[prefix]) and prefix and isinstance(ot[prefix - 1], Atom):
            prefix -= 1
        elif (space(nt[len(nt) - suffix - 1]) and suffix and
              isinstance(ot[len(ot) - suffix], Atom)):
            suffix -= 1
        else:
            break

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

    def same_after(i, j):
        """How many paragraphs right after old[i] and new[j] are the
        same in both (up to 30)."""
        n = 0
        while (i + 1 + n < len(old) and j + 1 + n < len(new) and n < 30
               and _same(old[i + 1 + n], new[j + 1 + n])):
            n += 1
        return n

    def between(i1, j1, i2, j2):
        """The change made by the paragraphs strictly between old[i1]
        and old[i2], and new[j1] and new[j2], or None. The context is
        old[i1] and old[i2] (in their old form, for edited paragraphs,
        whose own edits are separate changes), plus the paragraphs after
        old[i2] that are the same in both, so that a quiz added after a
        quiz can slide past an ENDQUIZ that git matched to the new one."""
        if i2 - i1 == 1 and j2 - j1 == 1:
            return None
        n = same_after(i2, j2) if i2 < len(old) else 0
        lo = max(i1, 0)
        ctx_old = old[lo:i2 + 1 + n]
        ctx_new = ([old[i1]] if i1 >= 0 else []) + new[j1 + 1:j2] + old[i2:i2 + 1 + n]
        c = _change(old, new, lo, max(j1, 0), ctx_old, ctx_new)
        if c and not c[1]:
            c[0].flags.append('not found')
        return c[0] if c else None

    # Between those, two ways to split up the changes: one change for
    # all of it, or pairing each changed paragraph with the next new one
    # that's the same paragraph edited (an edit within it), with the
    # rest as paragraphs inserted or deleted. Pairing keeps separate
    # edits apart (e.g., a new paragraph, an edited one, and a deleted
    # one); one change suits joining or splitting paragraphs. Use
    # whichever replaces less text.
    result = []
    bounds = [(-1, -1)] + fixed + [(len(old), len(new))]
    for (i1, j1), (i2, j2) in zip(bounds, bounds[1:]):
        if i2 - i1 == 1 and j2 - j1 == 1:
            continue
        whole = between(i1, j1, i2, j2)
        options = [[whole] if whole else []]
        pairs = []
        j = j1 + 1
        for i in range(i1 + 1, i2):
            if old[i].kind == 'empty':
                continue
            for k in range(j, j2):
                if _similar(old[i], new[k]):
                    pairs.append((i, k))
                    j = k + 1
                    break
        if pairs:
            split = [c[0] for c in (_change(old, new, i, k, [old[i]], [new[k]])
                                    for i, k in pairs) if c]
            points = [(i1, j1)] + pairs + [(i2, j2)]
            for (a, b), (c, d) in zip(points, points[1:]):
                ch = between(a, b, c, d)
                if ch:
                    split.append(ch)
            options.append(split)
        result += min(options, key=lambda cs: (
            sum(len(c.old_text) + len(c.new_text) for c in cs), len(cs)))
    result.sort(key=lambda c: (c.start, c.end), reverse=True)
    return old, result


# Search patterns. The doc finds text with findText() (RE2 syntax), and
# then the sidebar's code runs the same pattern as a JavaScript regular
# expression to get offsets, and this file checks it with Python's re;
# so patterns use only what all three treat alike: literal characters,
# escapes of punctuation, and character classes with \t, \v, and \xa0.
_WS = '[ \\t\\xa0\\v]+'  # \v is how findText() sees a soft line break
_QUOTES = {"'": "['‘’]", '‘': "['‘’]", '’': "['‘’]",
           '"': '["“”]', '“': '["“”]', '”': '["“”]'}


def pattern(text):
    """A search pattern for text, tolerant of differences between the
    Markdown and the doc that don't matter: any whitespace matches any
    other (the doc has tabs and no-break spaces; cleanup turns tabs into
    spaces), and curly and straight quotes match each other."""
    out = []
    for m in re.finditer(r'\s+|.', text, re.S):
        c = m.group()
        if c.isspace():
            out.append(_WS)
        elif c in _QUOTES:
            out.append(_QUOTES[c])
        elif c in '\\.^$|?*+()[]{}':
            out.append('\\' + c)
        else:
            out.append(c)
    return ''.join(out)


def _span(before, middle, after, para_start, para_end):
    return {'before': pattern(before), 'middle': pattern(middle),
            'after': pattern(after), 'para_start': para_start,
            'para_end': para_end, 'landmark': None}


def _matches(span, text):
    """Where span matches in a paragraph's text: (start, end) of its
    middle, for each match its anchors allow."""
    rx = re.compile(f"({span['before']})({span['middle']})({span['after']})")
    found = []
    for m in rx.finditer(text):
        if span['para_start'] and m.start() != 0:
            continue
        if span['para_end'] and m.end() != len(text):
            continue
        found.append((m.start(2), m.end(2)))
    return found


def _locate(paras, span, k, at):
    """Does span find paragraph k, with its middle at offsets at, and
    nothing else? With a landmark, the first match after it must be."""
    if span['landmark'] is not None:
        lm = span['landmark']
        lk = [i for i, p in enumerate(paras) if _matches(lm, p.text)]
        if len(lk) != 1:
            return False
        for i in range(lk[0] + 1, len(paras)):
            found = _matches(span, paras[i].text)
            if found:
                return (i, found[0]) == (k, at)
        return False
    hits = [(i, f) for i, p in enumerate(paras) for f in _matches(span, p.text)]
    return hits == [(k, at)]


def _word_cuts(atoms, lo, hi):
    """Character offsets in a paragraph where a word starts, from lo to
    hi, for growing context a word at a time."""
    cuts, off = [], 0
    for a in atoms:
        if lo <= off <= hi and re.match(r'\w', a.text):
            cuts.append(off)
        off += len(a.text)
    return cuts


def find_span(paras, k, a, b, keep_start=False, keep_end=False):
    """A span that finds the text from offset a to b in paragraph k,
    with as little context as makes it unique in paras (the old doc).
    keep_start or keep_end ties it to the paragraph's start or end (a
    span for one end of a change across paragraphs). Returns None if
    nothing, not even a landmark, makes it unique."""
    p = paras[k]
    text = p.text
    # Context boundaries a word at a time: before grows back from a,
    # after grows forward from b.
    befores = sorted({0} | set(_word_cuts(p.atoms, 0, a)), reverse=True)
    befores = [x for x in befores if x <= a]
    ends = [m.end() for m in re.finditer(r'\w+', text) if m.end() >= b]
    afters = [b] + [x for x in ends if x > b] + [len(text)]
    if keep_start:
        befores = [0]
    if keep_end:
        afters = [len(text)]
    # Start with up to two words each side.
    bi = min(2, len(befores) - 1) if a else 0
    ai = min(2, len(afters) - 1)
    if not a:
        befores = [0]
    while True:
        lo, hi = befores[bi], afters[ai]
        span = _span(text[lo:a], text[a:b], text[b:hi], lo == 0, hi == len(text))
        if _locate(paras, span, k, (a, b)):
            return span
        if bi == len(befores) - 1 and ai == len(afters) - 1:
            break
        if bi < len(befores) - 1:
            bi += 1
        if ai < len(afters) - 1:
            ai += 1
    # Not unique even as the whole paragraph (e.g., a quiz's ENDQUIZ):
    # also give the nearest unique paragraph before it as a landmark.
    for i in range(k - 1, -1, -1):
        q = paras[i]
        if not _locatable(q):
            continue
        lm = _span('', q.text, '', True, True)
        if sum(bool(_matches(lm, r.text)) for r in paras) != 1:
            continue
        span['landmark'] = lm
        if _locate(paras, span, k, (a, b)):
            return span
        break
    return None


def _summary(c):
    def short(t):
        t = ' '.join(t.split())
        return f'"{t}"' if len(t) <= 40 else f'"{t[:18]}…{t[-18:]}"'
    if not c.old_text:
        return 'Insert ' + short(c.new_text)
    if not c.new_text:
        return 'Delete ' + short(c.old_text)
    if c.old_text == c.new_text:
        return 'Reformat ' + short(c.old_text)
    return f'Replace {short(c.old_text)} with {short(c.new_text)}'


_CONTEXT = 80  # characters of old text to show around a change


def change_list(diff):
    """The change list the sidebar loads: changes(diff), each with spans
    to find where it goes in the doc (see find_span())."""
    paras, found = changes(diff)
    out = []
    for c in found:
        (sk, sa), (ek, eb) = c.start, c.end
        if sk == ek:
            start, end = find_span(paras, sk, sa, eb), None
            ok = start is not None
        else:
            start = find_span(paras, sk, sa, len(paras[sk].text), keep_end=True)
            end = find_span(paras, ek, 0, eb, keep_start=True)
            ok = start is not None and end is not None
        flags = list(c.flags)
        if not ok and 'not found' not in flags:
            flags.append('not found')
        # The old text around the change, for you to find it by hand if
        # the sidebar can't.
        before = paras[sk].text[:sa]
        after = paras[ek].text[eb:]
        if len(before) > _CONTEXT:
            before = '…' + before[-_CONTEXT:].split(' ', 1)[-1]
        if len(after) > _CONTEXT:
            after = after[:_CONTEXT].rsplit(' ', 1)[0] + '…'
        out.append({'id': c.id, 'kind': c.kind, 'summary': _summary(c),
                    'old_lines': list(c.old_lines), 'new_lines': list(c.new_lines),
                    'start': start, 'end': end, 'old_text': c.old_text,
                    'before_text': before, 'after_text': after,
                    'new_html': c.new_html, 'new_text': c.new_text,
                    'flags': flags})
    return {'format': 'md-to-gdocs 1', 'changes': out}


_FLAG_HELP = {
    'not found': "can't be found reliably in the doc; do it by hand",
    'internal link': 'has a link within the doc; add the link by hand',
    'image': 'has an image; do the image by hand',
    'unsupported': 'is next to a table or code; check it by hand',
    'list': 'has list items (pasting lists is untested); check them',
    'style': 'joins a paragraph of another kind (e.g., a heading); check its style',
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ('-h', '--help'):
        print(__doc__.strip())
        return 0
    try:
        if argv:
            with open(argv[0], encoding='utf-8') as f:
                diff = f.read()
        else:
            diff = sys.stdin.read()
        result = change_list(diff)
    except (DiffError, OSError) as e:
        print(f'md_to_gdocs: {e}', file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    changes_ = result['changes']
    print(f'{len(changes_)} change(s), last in the doc first:', file=sys.stderr)
    for n, c in enumerate(changes_, 1):
        print(f"  {n}. lines {c['old_lines'][0]}-{c['old_lines'][1]}: {c['summary']}",
              file=sys.stderr)
        for flag in c['flags']:
            print(f'     WARNING: {_FLAG_HELP.get(flag, flag)}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
