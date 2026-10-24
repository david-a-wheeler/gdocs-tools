// The "Doc tools" menu for gdocs-tools. Paste this into the doc's Apps
// Script project (Extensions > Apps Script) as a file named
// DocToolsMenu, next to the files of the tools you use.
//
// It has the project's only onOpen(): an Apps Script project's files
// share one namespace, so there can be only one. It adds an item for
// each tool whose function is in the project, so install only the tools
// you want. If the doc's project already has an onOpen(), merge it into
// this one.
//
// SPDX-FileCopyrightText: David A. Wheeler and contributors
// SPDX-License-Identifier: MIT

/**
 * @OnlyCurrentDoc
 */

function onOpen() {
  const menu = DocumentApp.getUi().createMenu('Doc tools');
  let items = 0;
  if (typeof mdToGdocsShowSidebar === 'function') {
    menu.addItem('Markdown changes sidebar', 'mdToGdocsShowSidebar');
    items++;
  }
  if (typeof linkifyCitations === 'function') {
    menu.addItem('Linkify citations', 'linkifyCitations');
    items++;
  }
  if (items > 0) menu.addToUi();
}
