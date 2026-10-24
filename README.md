# gdocs-tools

Tools for working on Google Docs, especially when a Markdown copy of
the doc is kept in git.

* [md-to-gdocs](#md-to-gdocs): recreate Markdown edits in a Google Doc
  (possibly as suggestions), one change at a time, from a sidebar in
  the doc. This lets you update an upstream Google Doc after editing a
  downstream Markdown file generated from the Google Doc.
* [linkifyCitations](#linkifycitations): turn each citation like
  `[Smith2026]` in a Google Doc into a link to the URL in its
  bibliography entry.

## The "Doc tools" menu

The tools share one menu in the doc, "Doc tools", from
[`DocToolsMenu.js`](DocToolsMenu.js). It adds an item for each tool
installed in the doc, so install only the tools you want. Add it once
per doc, along with your first tool:

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `DocToolsMenu`, and replace its
   contents with [`DocToolsMenu.js`](DocToolsMenu.js).
3. Add the tools' files (see below), save, and reload the doc.

An Apps Script project's files share one namespace, so each function
name can be defined only once in the whole project. In particular,
there can be only one `onOpen()`, and `DocToolsMenu` has it: if another
file in the project has one, the last file loaded silently wins, and
the "Doc tools" menu may vanish. If you need both, merge them into one
`onOpen()`. The tools' own names start with `mdToGdocs` or
`linkifyCitations`, so they won't clash.

To update a tool, replace its files' contents again, save, and reload
the doc.

## Installing everything in a doc

To install all the tools at once (or update them), in the Google Doc
choose Extensions > Apps Script. Then, for each file below, in order:

1. Run its command (in this directory), which copies the file to the
   clipboard. Here we show `wl-copy`, the command for copying a file into
   the clipboard on Linux systems using Wayland.
2. In the Apps Script editor, add a file of the kind and name shown
   (+ > Script or + > HTML; type just the name, since the editor adds
   the extension). To update a file, click its name instead.
   Note that the Google docs extension for scripts is `.gs` even though
   we use `.js` locally.
3. Click in the file's contents, press Ctrl+A to select them all, and
   press Ctrl+V to replace them.

```sh
wl-copy < DocToolsMenu.js        # Script: DocToolsMenu
wl-copy < MdToGdocs.js           # Script: MdToGdocs
wl-copy < MdToGdocsSidebar.html  # HTML:   MdToGdocsSidebar
wl-copy < linkifyCitations.js    # Script: linkifyCitations
```

Then save (Ctrl+S), and reload the doc; the "Doc tools" menu appears.

These commands use `wl-copy` (Linux with Wayland). Elsewhere, replace
`wl-copy < FILE` with:

* Linux with X11: `xclip -selection clipboard < FILE`
* macOS: `pbcopy < FILE`
* Windows (PowerShell): `Get-Content -Raw -Encoding UTF8 FILE | Set-Clipboard`.
  Avoid `clip < FILE`, which can garble the files' non-ASCII
  characters (e.g., curly quotes).

## md-to-gdocs

You edit a Markdown file that was generated from a Google Doc (using
File > Download > Markdown), and track its changes in git, as you'd
edit any Markdown. md-to-gdocs then walks you through recreating those
edits in the Google Doc, one change at a time. For each change, a
sidebar in the doc selects the old text (or puts your cursor where new
text goes) and puts the new text, formatted, on the clipboard; you
press Ctrl+V. In Suggesting mode, each paste becomes a suggestion that
others can review. If you don't need suggestions, it can apply most
changes directly instead.

Neither Apps Script nor the Google Docs API can create suggestions, so
a fully automatic tool isn't possible: for suggestions, the paste has
to come from you, in the editor. md-to-gdocs does everything else.

It has two parts:

* [`md_to_gdocs.py`](md_to_gdocs.py) (run locally) reads a git diff of
  the Markdown file and writes a *change list*: each change, how to
  find it in the doc, and the HTML to paste.
* [`MdToGdocs.js`](MdToGdocs.js) and
  [`MdToGdocsSidebar.html`](MdToGdocsSidebar.html) (installed in the
  doc) show the sidebar, find each change, and copy the new text (or
  apply it directly).

### Requirements

* Python 3 with [markdown-it-py](https://github.com/executablebooks/markdown-it-py)
  (on Debian or Ubuntu, `sudo apt install python3-markdown-it`).
* git.
* A Google Doc you can edit, with exactly one tab.
* The Markdown must be Google's Markdown export of the doc (File >
  Download > Markdown), either as is or cleaned up (e.g., by a
  `cleanup-markdown` script, as in OpenSSF's "Finding and Fixing
  Vulnerabilities Using AI" guide).

### Installing it in a doc (once per doc)

[Installing everything](#installing-everything-in-a-doc) has commands to
copy each file. To install just this tool:

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `MdToGdocs`, and replace its
   contents with [`MdToGdocs.js`](MdToGdocs.js).
3. Add an HTML file (+ > HTML) named exactly `MdToGdocsSidebar`, and
   replace its contents with
   [`MdToGdocsSidebar.html`](MdToGdocsSidebar.html).
4. Add the menu file, if it isn't there yet (see
   [above](#the-doc-tools-menu)).
5. Save, and reload the doc. The "Doc tools" menu has a "Markdown
   changes sidebar" item.
6. The first time you open the sidebar, Google asks you to approve
   access: only to the current doc and to show a sidebar.

### Using it

1. **Start from Markdown that matches the doc.** Export the doc as
   Markdown (cleaning it up if you do that), and commit it. That commit
   is BASE.
2. **Edit the Markdown** and commit (or not; the working tree works
   too).
3. **Make the change list,** where `TOOLS` is this directory:

   ```sh
   git diff -U100000 BASE -- FILE.md | python3 -I TOOLS/md_to_gdocs.py > ,changes.json
   ```

   `-U100000` gives the whole file as context, which the tool needs.
   It prints a numbered summary of the changes, and a warning for each
   one you'll need to check or do by hand.
4. **Open the sidebar:** Doc tools > Markdown changes sidebar. I
   recommend Suggesting mode (the pencil icon at the top right of the
   doc), so others can review each change; the mode is your choice.
5. **Load the change list:** copy it (e.g., `wl-copy < ,changes.json`
   on Wayland, `xclip -selection clipboard < ,changes.json` on X11, or
   `pbcopy < ,changes.json` on macOS), paste it into the sidebar, and
   click Load. The sidebar's file picker may not work; pasting does.
6. **If you don't need suggestions,** click "Directly apply plain
   changes" first (see [below](#directly-applying-plain-changes)).
7. **For each change**, click Select (or Next, Previous, or Done, which
   also select). The sidebar copies the new text, finds the change,
   selects its old text (or places your cursor), and returns focus to
   the doc. Check the selection, then:
   * press **Ctrl+V**, or,
   * if the change is a pure deletion (its heading ends in "DELETE"),
     press the **Delete key**: Ctrl+V of nothing does nothing in Docs.

   Check the result, then click **Done**: it marks the change
   Completed and goes to the next one that isn't. "Next incomplete"
   and "Previous incomplete" skip completed changes.
8. Close the sidebar whenever you like. When you reopen it, paste the
   same change list again; it remembers which changes are completed and
   where you were.

Changes go from the end of the doc to the start. A paragraph with a
pending suggestion looks like neither its old nor its new text to Apps
Script, so each change has to be found before anything above it
changes.

The sidebar shows, for each change, the text before it, the text to
change (struck through), the new text, and the text after it, with "¶"
marking each paragraph break. If the sidebar can't find a change, it
says why (e.g., "the text is in the doc 2 times"), and you can use that
context to do the change by hand. **Don't paste after a failure**: your
cursor hasn't moved, so the paste would go wherever it already was.

Finding a change takes about 3 s (mostly Apps Script starting up and
opening the doc). Sometimes a call from the sidebar gets no answer at
all; the sidebar gives up on it after 10 s and tries again, up to
three times, and says so while it waits.

### Directly applying plain changes

If you don't need suggestions, "Directly apply plain changes" does
most changes for you. It applies, as **direct edits, not suggestions**
(even in Suggesting mode), every incomplete change that:

* is plain text, except for bold and italics (no links, code,
  strikethrough, headings, or lists);
* has no warnings; and
* either stays within one paragraph, or only inserts new paragraphs
  (e.g., a quiz's feedback) at the start or end of an ordinary
  paragraph. It doesn't replace text with paragraphs or remove
  paragraph breaks.

Like every change, each one's place in the doc is unique: its text is
there exactly once, or, when its text repeats (e.g., "Answer: A"), it's
the first match after a nearby paragraph that's there exactly once.

Each new paragraph is a copy of the paragraph it's inserted next to,
with its text replaced, so it gets that paragraph's style, as when a
paste splits a paragraph. It skips a change whose text is in or right
next to formatted text, since the new text could pick up that
formatting, and one next to a heading, list item, table, or image.

It marks each one it applies Completed, and then reports how many it
applied and why it skipped any others; do those as usual. It asks
before it starts. To undo it, use File > Version history; I recommend
naming a version first (File > Version history > Name current version).

Use it before pasting any changes as suggestions, since a pending
suggestion can keep a change next to it from being found. Only one run
applies changes at a time, so clicking it again while a run is still
going is safe. It's also safe to run again later: an applied change's
old text is gone, so it isn't found again, and an insertion whose new
paragraphs are already there is skipped.

### What to do by hand

The summary and the sidebar warn about these:

* **Can't be found reliably** ("not found"): do the change by hand.
* **Links within the doc** (to a heading): the text is pasted without
  the link; add the link by hand.
* **Images**: do them by hand.
* **Tables and code blocks** nearby: check them.
* **List items**: pasting them is untested; check them.
* **Style**: the first or last new line joins a paragraph of another
  kind (e.g., a heading); check its style.

Soft line breaks (Shift+Enter) aren't supported: Google's Markdown
export writes them exactly like two separate paragraphs.

### How the Markdown maps to the doc

Google's Markdown export writes each paragraph on its own line, an
empty paragraph as a blank line, and two adjacent paragraphs as
consecutive lines (the first ending in two spaces). So md-to-gdocs
reads each line as a paragraph, however it ends (`\`, two spaces, or
nothing), and a blank line between two lines of ordinary text, or
after a list and before text, as an empty paragraph. Other blank lines
are just Markdown syntax. (In one large doc, this was right nearly
everywhere; before a list or a heading, a doc sometimes has an empty
paragraph that the export can't show.)

New text is pasted the same way: each line as a paragraph, with no
extra spacing, and new paragraphs anchored on an ordinary text
paragraph, so they get its style rather than a heading's.

Only the text a change touches, plus a little context, has to match
the doc. Elsewhere, the doc and BASE may differ. BASE and your edit
must be in the same form, both raw exports or both cleaned up, or the
diff is everything. Image URLs don't matter: they differ between
exports, and the tool compares images by their alt text.

### Not covered

* Docs with more than one tab.
* Other people's pending suggestions within a change or its context
  (the sidebar reports that it can't find the change).
* A change that spans an image within a paragraph.

## linkifyCitations

[`linkifyCitations.js`](linkifyCitations.js) is an Apps Script function
for docs that cite sources as `[ID]` and list them in a bibliography.
It reads the bibliography, and then makes each `[ID]` before the
bibliography a link to its source's URL. That way readers can click a
citation to go straight to the source, and you don't have to add those
links by hand. It also makes the URL in each bibliography entry a link.

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

[Installing everything](#installing-everything-in-a-doc) has commands to
copy each file. To install just this tool:

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `linkifyCitations`, and replace
   its contents with [`linkifyCitations.js`](linkifyCitations.js).
3. Add the menu file, if it isn't there yet (see
   [above](#the-doc-tools-menu)).
4. Save, and reload the doc. The "Doc tools" menu has a "Linkify
   citations" item.

### Running it

1. In the doc, choose Doc tools > Linkify citations. (Or, in the Apps
   Script editor, select `linkifyCitations` in the function list at the
   top, and click Run.)
2. The first time, Google asks you to approve access to the doc.
3. The doc shows how many citations it linked, or why it couldn't. It
   also warns about each ID that appears in the bibliography twice; the
   later entry's URL wins.

It's safe to rerun, e.g., after you add citations or change a URL: it
sets each link again from the current bibliography.

### Limitations

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

To run all the tests, in this directory:

```sh
python3 -I -m unittest -v
node --test
```

The md-to-gdocs Node tests run `MdToGdocs.js` with fake Google
objects, mostly end to end: `md_to_gdocs.py` makes change lists from
real Markdown edits, and a fake doc made from the same Markdown must
give back exactly each change's old text (or, when applying changes
directly, end up matching the new Markdown). To also check that a raw
export and its cleaned-up version give the same doc model, set
`MD_TO_GDOCS_RAW` and `MD_TO_GDOCS_CLEAN` to their paths.

## License

MIT; see [LICENSE](LICENSE).
