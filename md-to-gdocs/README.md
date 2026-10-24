# md-to-gdocs: Markdown edits to Google Docs suggestions

You edit a Markdown copy of a Google Doc in git, as you'd edit any
Markdown. md-to-gdocs then walks you through recreating those edits in
the Google Doc, one change at a time. For each change, a sidebar in the
doc selects the old text (or puts your cursor where new text goes) and
puts the new text, formatted, on the clipboard; you press Ctrl+V. In
Suggesting mode, each paste becomes a suggestion that others can
review.

Neither Apps Script nor the Google Docs API can create suggestions, so
a fully automatic tool isn't possible: the paste has to come from you,
in the editor. md-to-gdocs does everything else.

It has two parts:

* `md_to_gdocs.py` (run locally) reads a git diff of the Markdown file
  and writes a *change list*: each change, how to find it in the doc,
  and the HTML to paste.
* `MdToGdocs.js` and `MdToGdocsSidebar.html` (installed in the doc)
  show the sidebar, find each change, and copy the new text.

## Requirements

* Python 3 with [markdown-it-py](https://github.com/executablebooks/markdown-it-py)
  (on Debian or Ubuntu, `sudo apt install python3-markdown-it`).
* git.
* A Google Doc you can edit, with exactly one tab.
* The Markdown must be Google's Markdown export of the doc (File >
  Download > Markdown), either as is or cleaned up (e.g., by a
  `cleanup-markdown` script, as in OpenSSF's "Finding and Fixing
  Vulnerabilities Using AI" guide).

## Installing (once per doc)

1. In the Google Doc, choose Extensions > Apps Script.
2. Add a script file (+ > Script) named `MdToGdocs`, and replace its
   contents with `MdToGdocs.js`.
3. Add an HTML file (+ > HTML) named exactly `MdToGdocsSidebar`, and
   replace its contents with `MdToGdocsSidebar.html`.
4. If the project doesn't have it yet, add a script file named
   `DocToolsMenu`, and replace its contents with
   `../menu/DocToolsMenu.js`. It makes the "Doc tools" menu.
5. Save, and reload the doc. The "Doc tools" menu has a "Markdown
   changes sidebar" item.
6. The first time you open the sidebar, Google asks you to approve
   access: only to the current doc and to show a sidebar.

An Apps Script project's files share one namespace, so each function
name can be defined only once in the whole project. In particular,
there can be only one `onOpen()`, and `DocToolsMenu` has it: if another
file in the project has one, the last file loaded silently wins, and
the "Doc tools" menu may vanish. If you need both, merge them into one
`onOpen()`. All names in md-to-gdocs's own files start with
`mdToGdocs`, so they won't clash.

To update, replace the files' contents again, save, and reload the
doc.

## Using it

1. **Start from Markdown that matches the doc.** Export the doc as
   Markdown (cleaning it up if you do that), and commit it. That commit
   is BASE.
2. **Edit the Markdown** and commit (or not; the working tree works
   too).
3. **Make the change list:**

   ```sh
   git diff -U100000 BASE -- FILE.md | python3 -I md_to_gdocs.py > ,changes.json
   ```

   `-U100000` gives the whole file as context, which the tool needs.
   It prints a numbered summary of the changes, and a warning for each
   one you'll need to check or do by hand.
4. **Open the sidebar:** Doc tools > Markdown changes sidebar. I recommend
   Suggesting mode (the pencil icon at the top right of the doc), so
   others can review each change; the mode is your choice.
5. **Load the change list:** copy it (e.g., `wl-copy < ,changes.json`
   on Wayland, `xclip -selection clipboard < ,changes.json` on X11, or
   `pbcopy < ,changes.json` on macOS), paste it into the sidebar, and
   click Load. The sidebar's file picker may not work; pasting does.
6. **For each change**, click Select (or Next, Previous, or Done, which
   also select). The sidebar copies the new text, finds the change,
   selects its old text (or places your cursor), and returns focus to
   the doc. Check the selection, then:
   * press **Ctrl+V**, or,
   * if the change is a pure deletion (its heading ends in "DELETE"),
     press the **Delete key**: Ctrl+V of nothing does nothing in Docs.

   Check the result, then click **Done**: it marks the change
   Completed and goes to the next one that isn't. "Next incomplete"
   and "Previous incomplete" skip completed changes.
7. Close the sidebar whenever you like. When you reopen it, paste the
   same change list again; it remembers which changes are completed and
   where you were.

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

Use it before pasting any changes as suggestions. A paragraph with a
pending suggestion looks like neither its old nor its new text to Apps
Script, so a change next to one may not be found. Only one run applies
changes at a time, so clicking it again while a run is still going is
safe.

It's safe to run again: an applied change's old text is gone, so it
isn't found again, and an insertion whose new paragraphs are already
there is skipped.

### Notes

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

## What to do by hand

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

## How the Markdown maps to the doc

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

## Not covered

* Docs with more than one tab.
* Other people's pending suggestions within a change or its context
  (the sidebar reports that it can't find the change).
* A change that spans an image within a paragraph.

## Development

Tests, in this directory:

```sh
python3 -I -m unittest -v
node --test
```

The Node tests run `MdToGdocs.js` with fake Google objects, mostly end
to end: `md_to_gdocs.py` makes change lists from real Markdown edits,
and a fake doc made from the same Markdown must give back exactly each
change's old text. To also check that a raw export and its cleaned-up
version give the same doc model, set `MD_TO_GDOCS_RAW` and
`MD_TO_GDOCS_CLEAN` to their paths.

## License

MIT; see `../LICENSE`.
