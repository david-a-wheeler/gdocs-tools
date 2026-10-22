#!/usr/bin/env python3
"""Recreate Markdown edits in a Google Doc, as suggestions.

This is the local half of md-to-gdocs: it reads a git diff of a
Markdown file exported from a Google Doc, and works out each change
for the sidebar in the doc to apply. This part models the doc: the
paragraphs a Markdown file stands for, as the Google Doc has them.
"""

# SPDX-FileCopyrightText: OpenSSF project contributors
# SPDX-License-Identifier: MIT

import re
from dataclasses import dataclass

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
