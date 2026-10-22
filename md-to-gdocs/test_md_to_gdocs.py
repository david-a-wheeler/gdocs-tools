"""Tests for md_to_gdocs. Run: python3 -I -m unittest -v (in this
directory).

To also compare a raw Google Docs Markdown export with its cleaned-up
version, set MD_TO_GDOCS_RAW and MD_TO_GDOCS_CLEAN to their paths."""

# SPDX-FileCopyrightText: OpenSSF project contributors
# SPDX-License-Identifier: MIT

import os
import unittest
import unittest.mock

import contextlib
import difflib
import io
import json
import re

from md_to_gdocs import (Atom, DiffError, change_list, changes, doc_paras,
                         find_span, main, parse_diff, pattern)


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

    def test_blank_lines_next_to_headings_and_before_lists_are_syntax(self):
        md = '# Head\n\nText.\n\n* item\n\n## Sub\n'
        self.assertEqual(kinds_texts(md), [
            ('heading', 'Head'), ('text', 'Text.'), ('list', 'item'),
            ('heading', 'Sub')])

    def test_blank_line_after_list_before_text_is_empty_paragraph(self):
        self.assertEqual(kinds_texts('* item\n\nMore.\n'), [
            ('list', 'item'), ('empty', ''), ('text', 'More.')])

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


def diff(old, new):
    """A full-context unified diff, as git diff -U100000 makes."""
    return ''.join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        'a/f.md', 'b/f.md', n=100000))


def one_change(old, new):
    paras, found = changes(diff(old, new))
    assert len(found) == 1, found
    return paras, found[0]


P = '<p style="margin-top:0;margin-bottom:0">'


class ParseDiffTest(unittest.TestCase):
    def test_rebuilds_both_versions(self):
        old_md, new_md, line_map, old_ch, new_ch = parse_diff(
            diff('a\nb\nc\n', 'a\nB\nc\nd\n'))
        self.assertEqual((old_md, new_md), ('a\nb\nc\n', 'a\nB\nc\nd\n'))
        self.assertEqual(line_map, {1: 1, 3: 3})
        self.assertEqual((old_ch, new_ch), ({2}, {2, 4}))

    def test_errors(self):
        with self.assertRaisesRegex(DiffError, 'no changes'):
            parse_diff('')
        with self.assertRaisesRegex(DiffError, '-U100000'):
            parse_diff('@@ -5,3 +5,3 @@\n a\n-b\n+c\n')
        with self.assertRaisesRegex(DiffError, '-U100000'):
            parse_diff('@@ -1,2 +1,2 @@\n-a\n+b\n@@ -9 +9 @@\n-c\n+d\n')
        with self.assertRaisesRegex(DiffError, 'more than one file'):
            parse_diff('diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b\n'
                       'diff --git a/y b/y\n@@ -1 +1 @@\n-a\n+b\n')


class ChangesTest(unittest.TestCase):
    def test_replace_words_within_a_paragraph(self):
        paras, c = one_change('One.\n\nThe quick brown fox.\n\nTwo.\n',
                              'One.\n\nThe slow brown fox.\n\nTwo.\n')
        self.assertEqual((c.kind, c.old_text, c.new_text, c.new_html),
                         ('within', 'quick', 'slow', 'slow'))
        self.assertEqual((paras[c.start[0]].text, c.start[1], c.end[1]),
                         ('The quick brown fox.', 4, 9))
        self.assertEqual((c.old_lines, c.new_lines), ((3, 3), (3, 3)))

    def test_insert_and_delete_words(self):
        _, c = one_change('A b c.\n', 'A b new c.\n')
        self.assertEqual((c.kind, c.old_text, c.new_text), ('insert', '', ' new'))
        _, c = one_change('A b new c.\n', 'A b c.\n')
        self.assertEqual((c.kind, c.old_text, c.new_html), ('within', ' new', ''))

    def test_trailing_punctuation_isnt_kept_alone(self):
        _, c = one_change('Is foo bar.\n', 'Is foo baz.\n')
        self.assertEqual((c.old_text, c.new_text), ('bar.', 'baz.'))

    def test_new_paragraph_after_a_paragraph(self):
        # The tested recipe (spike K10): at the end of the paragraph
        # before, "<br><br>" for the break and the empty paragraph, then
        # the new line bare.
        paras, c = one_change('One.\n\nTwo.\n', 'One.\n\nNew.\n\nTwo.\n')
        self.assertEqual(c.kind, 'insert')
        self.assertEqual((paras[c.start[0]].text, c.start[1]), ('One.', 4))
        self.assertEqual(c.new_html, '<br><br>New.')
        self.assertEqual(c.new_text, '\n\nNew.')

    def test_new_quiz_after_a_quiz(self):
        quiz = ('QUIZ\\\nQ{n}. Why?\n\nA) a\\\nB) b\\\nC) c\\\nD) d\n\n'
                'Answer: A\\\nENDQUIZ')
        old = 'Text.\n\n' + quiz.format(n=1) + '\n\nMore.\n'
        new = 'Text.\n\n' + quiz.format(n=1) + '\\\n' + quiz.format(n=2) + '\n\nMore.\n'
        paras, c = one_change(old, new)
        self.assertEqual(c.kind, 'insert')
        self.assertEqual(paras[c.start[0]].text, 'ENDQUIZ')
        self.assertEqual(paras[c.start[0]].line, 12)
        self.assertEqual(c.new_html,
                         f'<br>{P}QUIZ</p>{P}Q2. Why?</p><br>{P}A) a</p>{P}B) b</p>'
                         f'{P}C) c</p>{P}D) d</p><br>{P}Answer: A</p>ENDQUIZ')

    def test_delete_a_paragraph(self):
        paras, c = one_change('One.\n\nGone.\n\nTwo.\n', 'One.\n\nTwo.\n')
        # From its start to the start of the next paragraph: the doc can
        # find both without widening the change.
        self.assertEqual((c.kind, c.old_text, c.new_html), ('across', 'Gone.\n\n', ''))
        self.assertEqual((paras[c.start[0]].text, c.start[1]), ('Gone.', 0))
        self.assertEqual((paras[c.end[0]].text, c.end[1]), ('Two.', 0))

    def test_replace_across_paragraphs(self):
        _, c = one_change('Keep this. Old end.\n\nOld start. Keep that.\n',
                          'Keep this. New text. Keep that.\n')
        self.assertEqual(c.kind, 'across')
        self.assertEqual(c.old_text, 'Old end.\n\nOld start')
        self.assertEqual(c.new_html, 'New text')

    def test_formatting_only(self):
        _, c = one_change('Make this bold.\n', 'Make **this** bold.\n')
        self.assertEqual((c.old_text, c.new_html), ('this', '<b>this</b>'))

    def test_link_isnt_split(self):
        _, c = one_change('See [the old page](https://a.org/).\n',
                          'See [the new page](https://a.org/).\n')
        self.assertEqual(c.old_text, 'the old page')
        self.assertEqual(c.new_html, '<a href="https://a.org/">the new page</a>')

    def test_flags(self):
        _, c = one_change('See it.\n', 'See [it](#heading).\n')
        self.assertEqual(c.flags, ['internal link'])
        _, c = one_change('Text.\n', 'Text.\n\n* a\n* b\n\nMore.\n')
        self.assertIn('list', c.flags)
        self.assertIn('<ul><li style="margin-top:0;margin-bottom:0">a</li>', c.new_html)

    def test_syntax_only_changes_are_not_changes(self):
        # E.g., a cleanup that adds "\" where the export had two spaces.
        self.assertEqual(changes(diff('One  \nTwo\n', 'One\\\nTwo\n'))[1], [])

    def test_nearby_changes_stay_apart(self):
        old = ('Keep.\n\nWe focus on one specific thing.\n\n'
               'Delete me.\n\nKeep too.\n')
        new = ('Keep.\n\nBrand new.\n\nWe focus on one particular thing.\n\n'
               'Keep too.\n')
        paras, found = changes(diff(old, new))
        self.assertEqual([(c.kind, c.old_text, c.new_text) for c in found], [
            ('across', 'Delete me.\n\n', ''),
            ('within', 'specific', 'particular'),
            ('insert', '', '\n\nBrand new.')])
        self.assertEqual([paras[c.start[0]].text for c in found],
                         ['Delete me.', 'We focus on one specific thing.', 'Keep.'])

    def test_several_changes_last_first(self):
        old = 'Alpha one.\n\nBeta two.\n\nGamma three.\n'
        new = 'Alpha 1.\n\nBeta two.\n\nGamma 3.\n'
        paras, found = changes(diff(old, new))
        self.assertEqual([(paras[c.start[0]].text, c.new_text) for c in found],
                         [('Gamma three.', '3.'), ('Alpha one.', '1.')])

    def test_id_survives_unrelated_edits(self):
        old = 'Alpha one.\n\nBeta two.\n\nGamma three.\n'
        _, a = changes(diff(old, old.replace('three', '3')))
        _, b = changes(diff(old, old.replace('three', '3').replace('one', '1')))
        self.assertEqual(a[0].id, b[0].id)


class PatternTest(unittest.TestCase):
    def test_tolerates_whitespace_and_quotes(self):
        rx = re.compile(pattern('It’s "a"  test (1.5)'))
        for text in ['It’s "a" test (1.5)', "It's “a”\ttest (1.5)",
                     'It’s "a"\xa0test (1.5)', 'It’s "a"\vtest (1.5)']:
            self.assertTrue(rx.fullmatch(text), text)
        self.assertFalse(rx.fullmatch('It’s "a" test (115)'))


class FindSpanTest(unittest.TestCase):
    def test_minimal_context(self):
        paras = doc_paras('The cat sat on the mat.\n\nThe dog sat on the log.\n')
        span = find_span(paras, 0, 8, 11)  # "sat"
        self.assertEqual(span['middle'], 'sat')
        self.assertTrue(span['before'] and span['after'])

    def test_context_grows_until_unique(self):
        paras = doc_paras('A b c d e f g.\n\nX b c d e f y.\n')
        span = find_span(paras, 0, 6, 7)  # "d", with "b c" and "e f" on each side
        self.assertEqual(span['para_start'] or span['para_end'], True)

    def test_landmark_for_repeated_paragraph(self):
        md = ('# One\n\nQUIZ\\\nAnswer: A\\\nENDQUIZ\n\n'
              '# Two\n\nQUIZ\\\nAnswer: B\\\nENDQUIZ\n')
        paras = doc_paras(md)
        k = [i for i, p in enumerate(paras) if p.text == 'ENDQUIZ'][1]
        span = find_span(paras, k, 7, 7)
        self.assertEqual(span['landmark']['middle'], pattern('Answer: B'))
        self.assertTrue(span['para_start'] and span['para_end'])

    def test_unfindable(self):
        paras = doc_paras('Same.\n\nSame.\n')
        self.assertIsNone(find_span(paras, 1, 0, 5))


class ChangeListTest(unittest.TestCase):
    def test_json_and_command_line(self):
        d = diff('Keep this. Old end.\n\nOld start. Keep that.\n',
                 'Keep this. New text. Keep that.\n')
        result = change_list(d)
        self.assertEqual(result['format'], 'md-to-gdocs 1')
        (c,) = result['changes']
        self.assertEqual((c['kind'], c['flags']), ('across', []))
        self.assertTrue(c['start']['para_end'] and c['end']['para_start'])
        self.assertEqual(c['summary'], 'Replace "Old end. Old start" with "New text"')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                unittest.mock.patch('sys.stdin', io.StringIO(d)):
            self.assertEqual(main([]), 0)
        self.assertEqual(json.loads(out.getvalue()), result)
        self.assertIn('1 change(s)', err.getvalue())

    def test_command_line_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                unittest.mock.patch('sys.stdin', io.StringIO('')):
            self.assertEqual(main([]), 1)
        self.assertIn('no changes', err.getvalue())


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
