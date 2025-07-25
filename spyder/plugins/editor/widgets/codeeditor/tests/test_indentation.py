# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
#

"""
Tests for the indentation feature
"""

# Third party imports
import pytest
from qtpy.QtGui import QTextCursor

# Local imports
from spyder.py3compat import to_text_string
from spyder.plugins.editor.widgets.codeeditor import CodeEditor


# --- Helper methods
# -----------------------------------------------------------------------------
def make_indent(editor, single_line=True, start_line=1):
    """Indent and return code."""
    editor.go_to_line(start_line)
    if not single_line:
        editor.moveCursor(QTextCursor.End, mode=QTextCursor.KeepAnchor)
    editor.indent()
    text = editor.toPlainText()
    return to_text_string(text)


def make_unindent(editor, single_line=True, start_line=1):
    """Unindent and return code."""
    editor.go_to_line(start_line)
    if not single_line:
        editor.moveCursor(QTextCursor.End, mode=QTextCursor.KeepAnchor)
    editor.unindent()
    text = editor.toPlainText()
    return to_text_string(text)

# --- Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def codeeditor_indent(codeeditor):
    """
    Setup CodeEditor with some text useful for folding related tests.
    """
    editor = codeeditor
    editor.set_indent_chars(" " * 2)
    return editor


# --- Tests
# -----------------------------------------------------------------------------
def test_single_line_indent(codeeditor_indent):
    """Test indentation in a single line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "self.b = 1\n"
            "print(self.b)\n"
            "\n"
            )
    expected = ("class a():\n"
                "  self.b = 1\n"
                "print(self.b)\n"
                "\n"
                )
    editor.set_text(text)
    # Indent line without spaces
    new_text = make_indent(editor, start_line=2)
    assert new_text == expected


def test_selection_indent(codeeditor_indent):
    """Test indentation with selection of more than one line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "self.b = 1\n"
            "print(self.b)\n"
            "\n"
            )
    expected = ("class a():\n"
                "  self.b = 1\n"
                "  print(self.b)\n"
                "  \n"
                )

    editor.set_text(text)
    # Toggle manually commented code
    new_text = make_indent(editor, single_line=False, start_line=2)
    assert new_text == expected


def test_fix_indentation(codeeditor_indent):
    """Test fix_indentation() method."""
    editor = codeeditor_indent
    # Contains tabs.
    original = ("\t\n"
                "class a():\t\n"
                "\tself.b = 1\n"
                "\tprint(self.b)\n"
                "\n"
                )
    # Fix indentation: replace tabs with indent_chars spaces
    fixed = ("  \n"
             "class a():  \n"
             "  self.b = 1\n"
             "  print(self.b)\n"
             "\n"
             )
    editor.set_text(original)
    editor.fix_indentation()
    assert to_text_string(editor.toPlainText()) == fixed
    assert editor.document().isModified()
    # Test that undo/redo works - spyder-ide/spyder#1754.
    editor.undo()
    assert to_text_string(editor.toPlainText()) == original
    assert not editor.document().isModified()
    editor.redo()
    assert to_text_string(editor.toPlainText()) == fixed
    assert editor.document().isModified()


def test_single_line_unindent(codeeditor_indent):
    """Test unindentation in a single line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "  self.b = 1\n"
            "print(self.b)\n"
            "\n"
            )
    expected = ("class a():\n"
                "self.b = 1\n"
                "print(self.b)\n"
                "\n"
                )
    editor.set_text(text)
    # Indent line without spaces
    new_text = make_unindent(editor, start_line=2)
    assert new_text == expected


def test_selection_unindent(codeeditor_indent):
    """Test unindentation with selection of more than one line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "  self.b = 1\n"
            "  print(self.b)\n"
            "  \n"
            )
    expected = ("class a():\n"
                "self.b = 1\n"
                "print(self.b)\n"
                "\n"
                )
    editor.set_text(text)
    # Toggle manually commented code
    new_text = make_unindent(editor, single_line=False, start_line=2)
    assert new_text == expected


def test_single_line_unindent_to_grid(codeeditor_indent):
    """Test unindentation in a single line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "   self.b = 1\n"
            "print(self.b)\n"
            "\n"
            )
    expected = ("class a():\n"
                "  self.b = 1\n"
                "print(self.b)\n"
                "\n"
                )
    editor.set_text(text)
    # Indent line without spaces
    new_text = make_unindent(editor, start_line=2)
    assert new_text == expected

    expected2 = ("class a():\n"
                 "self.b = 1\n"
                 "print(self.b)\n"
                 "\n"
                 )
    new_text2 = make_unindent(editor, start_line=2)
    assert new_text2 == expected2


def test_selection_unindent_to_grid(codeeditor_indent):
    """Test unindentation with selection of more than one line."""
    editor = codeeditor_indent
    text = ("class a():\n"
            "   self.b = 1\n"
            "   print(self.b)\n"
            "\n"
            )
    expected = ("class a():\n"
                "  self.b = 1\n"
                "  print(self.b)\n"
                "\n"
                )
    editor.set_text(text)
    # Toggle manually commented code
    new_text = make_unindent(editor, single_line=False, start_line=2)
    assert new_text == expected

    expected2 = ("class a():\n"
                 "self.b = 1\n"
                 "print(self.b)\n"
                 "\n"
                 )
    new_text2 = make_unindent(editor, single_line=False, start_line=2)
    assert new_text2 == expected2


if __name__ == "__main__":
    pytest.main()
