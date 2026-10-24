# gdocs-tools

Tools for working on Google Docs, especially when a Markdown copy of
the doc is kept in git.

* [md-to-gdocs](md-to-gdocs/README.md): recreate Markdown edits in a
  Google Doc (possibly as suggestions), one change at a time,
  from a sidebar in the doc. This lets you update an upstream Google doc
  after editing a downstream Markdown file generated from the Google doc

## md-to-gdocs in brief

You edit a Markdown file that was generated from a Google Doc
(using File-&gt; Download->&gt; Markdown).
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
4. Save, and reload the doc. A "Markdown changes" menu appears.
5. The first time you open the sidebar, Google asks you to approve
   access: only to the current doc and to show a sidebar.

If the doc's Apps Script project already has an `onOpen()`, merge the
two into one; otherwise the "Markdown changes" menu may vanish.

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
4. In the doc, choose Markdown changes > Open sidebar, and I recommend
   switching to Suggesting mode (the pencil icon at the top right).
5. Copy `,changes.json` to the clipboard, paste it into the sidebar,
   and click Load.
6. For each change, click Select (or Next, Previous, or Done). Check
   the selection, then press Ctrl+V (or, for a deletion, the Delete
   key). Check the result, and click Done.

You can close the sidebar any time; when you reopen it and paste the
same change list, it remembers where you were.

### Key limitations

* **You do each paste.** Neither Apps Script nor the Google Docs API
  can create suggestions, so md-to-gdocs can't apply changes by itself.
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

## License

MIT; see [LICENSE](LICENSE).
