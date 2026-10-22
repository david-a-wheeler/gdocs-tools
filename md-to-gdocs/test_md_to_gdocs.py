"""Tests for md_to_gdocs. Run: python3 -I -m unittest -v (in this
directory).

To also compare a raw Google Docs Markdown export with its cleaned-up
version, set MD_TO_GDOCS_RAW and MD_TO_GDOCS_CLEAN to their paths."""

import os
import unittest

from md_to_gdocs import Atom, doc_paras


def kinds_texts(markdown):
    return [(p.kind, p.text) for p in doc_paras(markdown)]


class DocParasTest(unittest.TestCase):
    def test_each_line_is_a_paragraph(self):
        # However the line ends: "\", two spaces, or nothing.
        self.assertEqual(kinds_texts('one\\\ntwo  \nthree\nfour\n'), [
            ('text', 'one'), ('text', 'two'), ('text', 'three'),
            ('text', 'four')])

    def test_blank_line_between_text_is_empty_paragraph(self):
        self.assertEqual(kinds_texts('one\n\ntwo\n\n\nthree\n'), [
            ('text', 'one'), ('empty', ''), ('text', 'two'),
            ('empty', ''), ('empty', ''), ('text', 'three')])

    def test_blank_lines_next_to_headings_and_lists_are_syntax(self):
        md = '# Head\n\nText.\n\n* item\n\nMore.\n\n## Sub\n'
        self.assertEqual(kinds_texts(md), [
            ('heading', 'Head'), ('text', 'Text.'), ('list', 'item'),
            ('text', 'More.'), ('heading', 'Sub')])

    def test_quiz(self):
        md = ('Before.\n\nQUIZ\\\nQ1. Which?\n\nA) a\\\nB) b\\\nC) c\\\n'
              'D) d\n\nAnswer: B\\\nENDQUIZ\\\nQUIZ\\\nQ2. Next?\n')
        self.assertEqual(kinds_texts(md), [
            ('text', 'Before.'), ('empty', ''), ('text', 'QUIZ'),
            ('text', 'Q1. Which?'), ('empty', ''), ('text', 'A) a'),
            ('text', 'B) b'), ('text', 'C) c'), ('text', 'D) d'),
            ('empty', ''), ('text', 'Answer: B'), ('text', 'ENDQUIZ'),
            ('text', 'QUIZ'), ('text', 'Q2. Next?')])

    def test_line_numbers(self):
        paras = doc_paras('# H\n\nOne\ntwo\n\nthree\n')
        self.assertEqual([(p.line, p.text) for p in paras], [
            (1, 'H'), (3, 'One'), (4, 'two'), (5, ''), (6, 'three')])

    def test_lists(self):
        paras = doc_paras('1. one\n   1. nested\n2. two\n\n* bullet\n')
        self.assertEqual(
            [(p.kind, p.level, p.ordered, p.text) for p in paras], [
                ('list', 0, True, 'one'), ('list', 1, True, 'nested'),
                ('list', 0, True, 'two'), ('list', 0, False, 'bullet')])

    def test_block_quote_lines_keep_their_marker(self):
        self.assertEqual(kinds_texts('Text.\n\n> Quoted\\\nnot quoted\n'), [
            ('text', 'Text.'), ('empty', ''), ('text', '> Quoted'),
            ('text', 'not quoted')])

    def test_escapes_and_entities_are_plain_text(self):
        # Google's export escapes these; the doc shows them plainly.
        self.assertEqual(kinds_texts('a\\*b \\[c\\] https\\://x.org &amp;\n'),
                         [('text', 'a*b [c] https://x.org &')])

    def test_formatting(self):
        (p,) = doc_paras('*em* **strong** `co de` ~~s~~ [link](https://x.org/)\n')
        self.assertEqual(p.text, 'em strong co de s link')
        marked = {a.text: (a.marks, a.href) for a in p.atoms if a.text.strip()}
        self.assertEqual(marked['em'], (frozenset({'em'}), None))
        self.assertEqual(marked['strong'], (frozenset({'strong'}), None))
        self.assertEqual(marked['co'], (frozenset({'code'}), None))
        self.assertEqual(marked['s'], (frozenset({'s'}), None))
        self.assertEqual(marked['link'], (frozenset(), 'https://x.org/'))

    def test_autolink(self):
        (p,) = doc_paras('See <https://x.org/a>.\n')
        self.assertEqual(p.text, 'See https://x.org/a.')
        self.assertEqual(p.atoms[2], Atom('https', href='https://x.org/a'))

    def test_image_is_an_atom_without_text(self):
        (p,) = doc_paras('![Alt text](images/x.png){width=10 height=20}\n')
        self.assertEqual(p.text, '')
        self.assertEqual([a.image for a in p.atoms], ['Alt text'])

    def test_unsupported(self):
        paras = doc_paras('Text.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nMore.\n')
        self.assertEqual([(p.kind, p.line, p.end) for p in paras], [
            ('text', 1, 1), ('unsupported', 3, 5), ('text', 7, 7)])

    def test_cleanup_additions_are_skipped(self):
        md = ('# Title\n<!-- markdownlint-disable-file MD025 -->\n'
              '<!-- A comment. -->\n\nText.\n')
        self.assertEqual(kinds_texts(md), [('heading', 'Title'),
                                           ('text', 'Text.')])

    def test_raw_export_quirks(self):
        # Heading IDs, and the flat table of contents (with escapes).
        md = ('# Title\n\n[Intro](#intro)\n\n[A (b)](#a-\\(b\\))\n\n'
              '# Intro {#intro}\n\nText.\n')
        self.assertEqual(kinds_texts(md), [
            ('heading', 'Title'), ('heading', 'Intro'), ('text', 'Text.')])


@unittest.skipUnless(os.environ.get('MD_TO_GDOCS_RAW')
                     and os.environ.get('MD_TO_GDOCS_CLEAN'),
                     'set MD_TO_GDOCS_RAW and MD_TO_GDOCS_CLEAN')
class RawVersusCleanTest(unittest.TestCase):
    def test_same_doc_paras(self):
        # cleanup-markdown turns tabs into spaces, so ignore that.
        def model(var):
            with open(os.environ[var], encoding='utf-8') as f:
                return [(p.kind, p.text.replace('\t', ' '))
                        for p in doc_paras(f.read())]
        self.assertEqual(model('MD_TO_GDOCS_RAW'), model('MD_TO_GDOCS_CLEAN'))


if __name__ == '__main__':
    unittest.main()
