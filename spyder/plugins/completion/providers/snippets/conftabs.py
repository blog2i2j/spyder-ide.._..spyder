# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
Text snippets configuration tabs.
"""

# Standard library imports
import copy
import os.path as osp

# Third party imports
from qtpy.compat import getsavefilename, getopenfilename
from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QFileDialog,
)

# Local imports
from spyder.api.preferences import SpyderPreferencesTab
from spyder.api.widgets.comboboxes import SpyderComboBox
from spyder.config.base import _
from spyder.config.snippets import SNIPPETS
from spyder.plugins.completion.providers.snippets.widgets import (
    SnippetModelsProxy, SnippetTable, SUPPORTED_LANGUAGES_PY, PYTHON_POS)
from spyder.utils.icon_manager import ima
from spyder.utils.stylesheet import AppStyle


LSP_URL = "https://microsoft.github.io/language-server-protocol"


class SnippetsConfigTab(SpyderPreferencesTab):
    TITLE = _('Snippets')

    def __init__(self, parent):
        super().__init__(parent)
        self.snippets_language = 'python'
        grammar_url = (
            "<a href=\"{0}/specifications/specification-current#snippet_syntax\">"
            "{1}</a>".format(LSP_URL, _('the LSP grammar')))
        snippets_info_label = QLabel(
            _("Spyder allows to define custom completion snippets to use "
              "in addition to the ones offered by the Language Server "
              "Protocol (LSP). Each snippet should follow {}.<br><br> "
              "<b>Note:</b> All changes will be effective only when applying "
              "the settings").format(grammar_url))
        snippets_info_label.setOpenExternalLinks(True)
        snippets_info_label.setWordWrap(True)
        snippets_info_label.setAlignment(Qt.AlignJustify)

        self.snippets_language_cb = SpyderComboBox(self)
        self.snippets_language_cb.setToolTip(
            _('Programming language provided by the LSP server'))
        self.snippets_language_cb.setMinimumWidth(250)
        self.snippets_language_cb.addItems(SUPPORTED_LANGUAGES_PY)
        self.snippets_language_cb.setCurrentIndex(PYTHON_POS)
        self.snippets_language_cb.currentTextChanged.connect(
            self.change_language_snippets)

        snippet_lang_label = QLabel(_('Language:'))
        snippet_lang_layout = QHBoxLayout()
        snippet_lang_layout.addWidget(snippet_lang_label)
        snippet_lang_layout.addWidget(self.snippets_language_cb)
        snippet_lang_layout.addStretch()

        snippet_table_label = QLabel(_('Available snippets:'))
        self.snippets_proxy = SnippetModelsProxy(self)
        self.snippets_table = SnippetTable(
            self, self.snippets_proxy, language=self.snippets_language)
        self.snippets_table.setMaximumHeight(200)

        snippets_table_layout = QHBoxLayout()
        snippets_table_layout.addSpacing(2 * AppStyle.MarginSize)
        snippets_table_layout.addWidget(self.snippets_table)
        snippets_table_layout.addSpacing(2 * AppStyle.MarginSize)

        # Buttons
        self.new_snippet_btn = QPushButton(icon=ima.icon("edit_add"))
        self.new_snippet_btn.setToolTip(_("Create a new snippet"))
        self.delete_snippet_btn = QPushButton(icon=ima.icon("editclear"))
        self.delete_snippet_btn.setToolTip(
            _("Delete currently selected snippet")
        )
        self.delete_snippet_btn.setEnabled(False)
        self.reset_snippets_btn = QPushButton(icon=ima.icon("restart"))
        self.reset_snippets_btn.setToolTip(_("Reset to default values"))
        self.export_snippets_btn = QPushButton(icon=ima.icon("fileexport"))
        self.export_snippets_btn.setToolTip(_("Export snippets to JSON"))
        self.import_snippets_btn = QPushButton(icon=ima.icon("fileimport"))
        self.import_snippets_btn.setToolTip(_("Import snippets from JSON"))

        # Slots connected to buttons
        self.new_snippet_btn.clicked.connect(self.create_new_snippet)
        self.reset_snippets_btn.clicked.connect(self.reset_default_snippets)
        self.delete_snippet_btn.clicked.connect(self.delete_snippet)
        self.export_snippets_btn.clicked.connect(self.export_snippets)
        self.import_snippets_btn.clicked.connect(self.import_snippets)

        # Buttons layout
        btns = [
            self.new_snippet_btn,
            self.delete_snippet_btn,
            self.reset_snippets_btn,
            self.export_snippets_btn,
            self.import_snippets_btn
        ]
        sn_buttons_layout = QHBoxLayout()
        sn_buttons_layout.addStretch()
        for btn in btns:
            btn.setIconSize(
                QSize(AppStyle.ConfigPageIconSize, AppStyle.ConfigPageIconSize)
            )
            sn_buttons_layout.addWidget(btn)
        sn_buttons_layout.addStretch()

        # Snippets layout
        snippets_layout = QVBoxLayout()
        snippets_layout.addWidget(snippets_info_label)
        snippets_layout.addSpacing(3 * AppStyle.MarginSize)
        snippets_layout.addLayout(snippet_lang_layout)
        snippets_layout.addSpacing(3 * AppStyle.MarginSize)
        snippets_layout.addWidget(snippet_table_label)
        snippets_layout.addLayout(snippets_table_layout)
        snippets_layout.addSpacing(AppStyle.MarginSize)
        snippets_layout.addLayout(sn_buttons_layout)

        self.setLayout(snippets_layout)

    def create_new_snippet(self):
        self.snippets_table.show_editor(new_snippet=True)

    def delete_snippet(self):
        idx = self.snippets_table.currentIndex().row()
        self.snippets_table.delete_snippet(idx)
        self.set_modified(True)
        self.delete_snippet_btn.setEnabled(False)

    def reset_default_snippets(self):
        language = self.snippets_language_cb.currentText()
        default_snippets_lang = copy.deepcopy(
            SNIPPETS.get(language.lower(), {}))
        self.snippets_proxy.reload_model(
            language.lower(), default_snippets_lang)
        self.snippets_table.reset_plain()
        self.set_modified(True)

    def change_language_snippets(self, language):
        self.snippets_table.update_language_model(language)

    def export_snippets(self):
        filename, _selfilter = getsavefilename(
            self, _("Save snippets"),
            'spyder_snippets.json',
            filters='JSON (*.json)',
            selectedfilter='',
            options=QFileDialog.HideNameFilterDetails)

        if filename:
            filename = osp.normpath(filename)
            self.snippets_proxy.export_snippets(filename)

    def import_snippets(self):
        filename, _sf = getopenfilename(
            self,
            _("Load snippets"),
            filters='JSON (*.json)',
            selectedfilter='',
            options=QFileDialog.HideNameFilterDetails,
        )

        if filename:
            filename = osp.normpath(filename)
            valid, total, errors = self.snippets_proxy.import_snippets(
                filename)
            modified = True
            if len(errors) == 0:
                QMessageBox.information(
                    self,
                    _('All snippets imported'),
                    _('{0} snippets were loaded successfully').format(valid),
                    QMessageBox.Ok)
            else:
                if 'loading' in errors:
                    modified = False
                    QMessageBox.critical(
                        self,
                        _('JSON malformed'),
                        _('There was an error when trying to load the '
                          'provided JSON file: <tt>{0}</tt>').format(
                              errors['loading']),
                        QMessageBox.Ok
                    )
                elif 'validation' in errors:
                    modified = False
                    QMessageBox.critical(
                        self,
                        _('Invalid snippet file'),
                        _('The provided snippet file does not comply with '
                          'the Spyder JSON snippets spec and therefore it '
                          'cannot be loaded.<br><br><tt>{}</tt>').format(
                              errors['validation']),
                        QMessageBox.Ok
                    )
                elif 'syntax' in errors:
                    syntax_errors = errors['syntax']
                    msg = []
                    for syntax_key in syntax_errors:
                        syntax_err = syntax_errors[syntax_key]
                        msg.append('<b>{0}</b>: {1}'.format(
                            syntax_key, syntax_err))
                    err_msg = '<br>'.join(msg)

                    QMessageBox.warning(
                        self,
                        _('Incorrect snippet format'),
                        _('Spyder was able to load {0}/{1} snippets '
                          'correctly, please check the following snippets '
                          'for any syntax errors: '
                          '<br><br>{2}').format(valid, total, err_msg),
                        QMessageBox.Ok
                    )
            self.set_modified(modified)

    def apply_settings(self):
        return self.snippets_proxy.save_snippets()
