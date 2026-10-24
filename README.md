# gdocs-tools

Tools for working on Google Docs, especially when a Markdown copy of
the doc is kept in git.

* [md-to-gdocs](md-to-gdocs/README.md): recreate Markdown edits in a
  Google Doc (possibly as suggestions), one change at a time,
  from a sidebar in the doc. This lets you update an upstream Google doc
  after editing a downstream Markdown file generated from the Google doc.
* [linkifyCitations](linkify/linkifyCitations.js): turn each citation
  like `[Smith2026]` in a Google Doc into a link to the URL in its
  bibliography entry.

## The "Doc tools" menu

The tools share one menu in the doc, "Doc tools", from
[`menu/DocToolsMenu.js`](menu/DocToolsMenu.js). It adds an item for
each tool installed in the doc, so install only the tools you want.
Add it once per doc, along with your first tool:

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `DocToolsMenu`, and replace its
   contents with [`menu/DocToolsMenu.js`](menu/DocToolsMenu.js).
3. Add the tools' files (see below), save, and reload the doc.

An Apps Script project's files share one namespace, so there can be
only one `onOpen()`, and this file has it. If the doc's project already
has an `onOpen()`, merge the two into one; otherwise the "Doc tools"
menu may vanish.

## md-to-gdocs in brief

You edit a Markdown file that was generated from a Google Doc
(using File > Download > Markdown).
Track the markdown file's changes using git.

The tool md-to-gdocs turns that
git diff into a list of changes, which you can upload to Google docs.
A sidebar in the Google doc walks you
through them: for each change, it selects the old text and puts the
new text, formatted, on the clipboard, and you press Ctrl+V. In
Suggesting mode, each paste becomes a suggestion others can review.
See [its README](md-to-gdocs/README.md) for the details.

You need Python 3 with
[markdown-it-py](https://github.com/executablebooks/markdown-it-py)
(on Debian or Ubuntu, `sudo apt install python3-markdown-it`), git,
and a Google Doc you can edit.

### Installing it in a doc (once per doc)

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `MdToGdocs`, and replace its
   contents with [`md-to-gdocs/MdToGdocs.js`](md-to-gdocs/MdToGdocs.js).
3. Add an HTML file (+ > HTML) named exactly `MdToGdocsSidebar`, and
   replace its contents with
   [`md-to-gdocs/MdToGdocsSidebar.html`](md-to-gdocs/MdToGdocsSidebar.html).
4. Add the menu file, if it isn't there yet (see
   [above](#the-doc-tools-menu)).
5. Save, and reload the doc. The "Doc tools" menu has a "Markdown
   changes sidebar" item.
6. The first time you open the sidebar, Google asks you to approve
   access: only to the current doc and to show a sidebar.

### Putting a Markdown change into the doc

1. Export the doc as Markdown (File > Download > Markdown), clean it up
   if you do that, and commit it. That commit is BASE.
2. Edit the Markdown, and commit it (or leave it in the working tree).
3. Make the change list, where `TOOLS` is this directory:

   ```sh
   git diff -U100000 BASE -- FILE.md |
     python3 -I TOOLS/md-to-gdocs/md_to_gdocs.py > ,changes.json
   ```

   It prints a numbered summary of the changes, and a warning for each
   one you'll need to check or do by hand.
4. In the doc, choose Doc tools > Markdown changes sidebar, and I recommend
   switching to Suggesting mode (the pencil icon at the top right).
5. Copy `,changes.json` to the clipboard, paste it into the sidebar,
   and click Load.
6. For each change, click Select (or Next, Previous, or Done). Check
   the selection, then press Ctrl+V (or, for a deletion, the Delete
   key). Check the result, and click Done.

If you don't need suggestions, first click "Directly apply plain
changes". It applies every change that's plain text (bold and italics
are fine), has no warnings, and either stays within one paragraph or
only inserts new paragraphs (e.g., quiz feedback), as direct edits
(not suggestions), and marks them completed. Then use "Next
incomplete" to do the rest as above. To undo it, use File > Version
history.

You can close the sidebar any time; when you reopen it and paste the
same change list, it remembers where you were.

### Key limitations

* **You do each paste, for suggestions.** Neither Apps Script nor the
  Google Docs API can create suggestions, so md-to-gdocs can't create
  them by itself. It can directly apply only plain changes (bold and
  italics are fine) that stay within a paragraph or insert new
  paragraphs.
  Each change takes a few seconds, so a large edit may take a while.
* **The Markdown must come from the doc.** It must be Google's Markdown
  export of the doc, as is or cleaned up, and BASE and your edit must
  be in the same form. The text near each change must still match the
  doc.
* **Some changes need you.** Do images by hand, add links to headings
  within the doc by hand, and check changes near tables, code blocks,
  and list items. A change the sidebar can't find reliably, e.g.,
  because its text appears twice, is shown with its context so you can
  do it by hand.
* **Not supported:** docs with more than one tab, soft line breaks
  (Shift+Enter), changes that span an image within a paragraph, and
  changes within or next to other people's pending suggestions.

## linkifyCitations in brief

linkifyCitations is an Apps Script function for docs that cite sources
as `[ID]` and list them in a bibliography. It reads the bibliography,
and then makes each `[ID]` before the bibliography a link to its
source's URL. That way readers can click a citation to go straight to
the source, and you don't have to add those links by hand. It also
makes the URL in each bibliography entry a link.

It expects:

* A paragraph whose whole text is "Bibliography" (in any case), e.g.,
  a heading. Everything after it is the bibliography.
* Bibliography entries that each start with `[ID]` and contain a URL
  starting with `http://` or `https://`, e.g.,
  `[Smith2026] Jane Smith, "A Paper", 2026. https://example.com/paper`.
  An ID can't contain spaces or `]`.
* Citations elsewhere in the doc written as `[ID]`, e.g.,
  `as shown in [Smith2026]`. The link goes on the ID, not the brackets.

### Installing it in a doc (once per doc)

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `linkifyCitations`, and replace
   its contents with
   [`linkify/linkifyCitations.js`](linkify/linkifyCitations.js).
3. Add the menu file, if it isn't there yet (see
   [above](#the-doc-tools-menu)).
4. Save, and reload the doc. The "Doc tools" menu has a "Linkify
   citations" item.

It can share an Apps Script project with md-to-gdocs; their names don't
clash.

### Running it

1. In the doc, choose Doc tools > Linkify citations. (Or, in the Apps
   Script editor, select `linkifyCitations` in the function list at the
   top, and click Run.)
2. The first time, Google asks you to approve access to the doc.
3. The doc shows how many citations it linked, or why it couldn't. It also warns about each ID that appears
   in the bibliography twice; the later entry's URL wins.

It's safe to rerun, e.g., after you add citations or change a URL: it
sets each link again from the current bibliography.

### Key limitations

* **It edits the doc directly**, not as suggestions, even in Suggesting
  mode. To undo it, use File > Version history.
* **Only the main body of the first tab**: not footnotes, headers, or
  other tabs. Citations after the bibliography aren't linked either.
* **It only adds and updates links.** It doesn't remove a link from a
  citation whose bibliography entry you deleted, and it doesn't report
  citations with no bibliography entry.
* **Any `[ID]` text matching a bibliography ID becomes a link**, even
  if it isn't meant as a citation.

## Development

To run all the tests, from this directory:

```sh
(cd md-to-gdocs && python3 -I -m unittest)
node --test
```

## License

MIT; see [LICENSE](LICENSE).
