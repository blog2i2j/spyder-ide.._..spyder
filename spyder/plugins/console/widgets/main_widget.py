# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
Main Console widget.
"""

# pylint: disable=C0103
# pylint: disable=R0903
# pylint: disable=R0911
# pylint: disable=R0201

# Standard library imports
import logging
import os
import os.path as osp
import sys

# Third party imports
from qtpy.compat import getopenfilename
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtWidgets import QAction, QInputDialog, QLineEdit, QVBoxLayout
from qtpy import PYSIDE2, PYSIDE6

# Local imports
from spyder.api.exceptions import SpyderAPIError
from spyder.api.plugin_registration.registry import PLUGIN_REGISTRY
from spyder.api.translations import _
from spyder.api.widgets.main_widget import PluginMainWidget
from spyder.api.config.decorators import on_conf_change
from spyder.utils.installers import InstallerInternalError
from spyder.config.base import DEV, get_debug_level
from spyder.plugins.console.widgets.internalshell import InternalShell
from spyder.py3compat import to_text_string
from spyder.utils.environ import EnvDialog
from spyder.utils.misc import (get_error_match, getcwd_or_home,
                               remove_backslashes)
from spyder.utils.qthelpers import DialogManager, mimedata2url
from spyder.widgets.collectionseditor import CollectionsEditor
from spyder.widgets.findreplace import FindReplace
from spyder.widgets.reporterror import SpyderErrorDialog


# Logging
logger = logging.getLogger(__name__)


# --- Constants
# ----------------------------------------------------------------------------
class ConsoleWidgetActions:
    # Triggers
    Environment = 'environment_action'
    ExternalEditor = 'external_editor_action'
    MaxLineCount = 'max_line_count_action'
    # The name of the action needs to match name of the shortcut
    # so 'Quit' is used instead of something like 'quit_action'
    Quit = 'Quit'
    Run = 'run_action'
    SysPath = 'sys_path_action'

    # Toggles
    ToggleCodeCompletion = 'toggle_code_completion_action'
    ToggleWrap = 'toggle_wrap_action'


class ConsoleWidgetMenus:
    InternalSettings = 'internal_settings_submenu'


class ConsoleWidgetOptionsMenuSections:
    Run = 'run_section'
    Quit = 'quit_section'


class ConsoleWidgetInternalSettingsSubMenuSections:
    Main = 'main'


# --- Widgets
# ----------------------------------------------------------------------------
class ConsoleWidget(PluginMainWidget):
    # --- Signals
    # This signal emits a parsed error traceback text so we can then
    # request opening the file that traceback comes from in the Editor.
    sig_edit_goto_requested = Signal(str, int, str)

    # TODO: I do not think we use this?
    sig_focus_changed = Signal()

    # Emit this when the interpreter buffer is flushed
    sig_refreshed = Signal()

    # Request to show a status message on the main window
    sig_show_status_requested = Signal(str)

    sig_help_requested = Signal(dict)
    """
    This signal is emitted to request help on a given object `name`.

    Parameters
    ----------
    help_data: dict
        Example `{'name': str, 'ignore_unknown': bool}`.
    """

    def __init__(self, name, plugin, parent=None):
        super().__init__(name, plugin, parent)

        logger.info("Initializing...")

        # Traceback MessageBox
        self.error_traceback = ''
        self.dismiss_error = False

        # Header message
        message = _(
            "Spyder Internal Console\n\n"
            "This console is used to report application\n"
            "internal errors and to inspect Spyder\n"
            "internals with the following commands:\n"
            "  spy.app, spy.window, dir(spy)\n\n"
            "Please do not use it to run your code\n\n"
        )

        # Options that come from the command line
        cli_options = plugin.get_command_line_options()
        profile = cli_options.profile
        multithreaded = cli_options.multithreaded

        # Widgets
        self.dialog_manager = DialogManager()
        self.error_dlg = None
        self.shell = InternalShell(  # TODO: Move to use SpyderWidgetMixin?
            parent=parent,
            commands=[],
            message=message,
            max_line_count=self.get_conf('max_line_count'),
            profile=profile,
            multithreaded=multithreaded,
        )
        self.find_widget = FindReplace(self)

        # Setup
        self.setAcceptDrops(True)
        self.find_widget.set_editor(self.shell)
        self.find_widget.hide()
        self.shell.toggle_wrap_mode(self.get_conf('wrap'))

        # Layout
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.addWidget(self.shell)
        layout.addWidget(self.find_widget)
        self.setLayout(layout)

        # Signals
        self.shell.sig_help_requested.connect(self.sig_help_requested)
        self.shell.sig_exception_occurred.connect(self.handle_exception)
        self.shell.sig_focus_changed.connect(self.sig_focus_changed)
        self.shell.sig_go_to_error_requested.connect(self.go_to_error)
        self.shell.sig_redirect_stdio_requested.connect(
            self.sig_redirect_stdio_requested)
        self.shell.sig_refreshed.connect(self.sig_refreshed)
        self.shell.sig_show_status_requested.connect(
            lambda msg: self.sig_show_status_message.emit(msg, 0))

    # --- PluginMainWidget API
    # ------------------------------------------------------------------------
    def get_title(self):
        return _('Internal console')

    def setup(self):
        # TODO: Move this to the shell
        self.quit_action = self.create_action(
            ConsoleWidgetActions.Quit,
            text=_("&Quit"),
            tip=_("Quit"),
            icon=self.create_icon('exit'),
            triggered=self.sig_quit_requested,
            context=Qt.ApplicationShortcut,
            shortcut_context="_",
            register_shortcut=True,
            menurole=QAction.QuitRole
        )
        run_action = self.create_action(
            ConsoleWidgetActions.Run,
            text=_("&Run..."),
            tip=_("Run a Python file"),
            icon=self.create_icon('run_small'),
            triggered=self.run_script,
        )
        environ_action = self.create_action(
            ConsoleWidgetActions.Environment,
            text=_("Environment variables..."),
            tip=_("Show and edit environment variables (for current "
                  "session)"),
            icon=self.create_icon('environ'),
            triggered=self.show_env,
        )
        syspath_action = self.create_action(
            ConsoleWidgetActions.SysPath,
            text=_("Show sys.path contents..."),
            tip=_("Show (read-only) sys.path"),
            icon=self.create_icon('syspath'),
            triggered=self.show_syspath,
        )
        buffer_action = self.create_action(
            ConsoleWidgetActions.MaxLineCount,
            text=_("Buffer..."),
            tip=_("Set maximum line count"),
            triggered=self.change_max_line_count,
        )
        exteditor_action = self.create_action(
            ConsoleWidgetActions.ExternalEditor,
            text=_("External editor path..."),
            tip=_("Set external editor executable path"),
            triggered=self.change_exteditor,
        )
        wrap_action = self.create_action(
            ConsoleWidgetActions.ToggleWrap,
            text=_("Wrap lines"),
            toggled=lambda val: self.set_conf('wrap', val),
            initial=self.get_conf('wrap'),
        )
        codecompletion_action = self.create_action(
            ConsoleWidgetActions.ToggleCodeCompletion,
            text=_("Automatic code completion"),
            toggled=lambda val: self.set_conf('codecompletion/auto', val),
            initial=self.get_conf('codecompletion/auto'),
        )

        # Submenu
        internal_settings_menu = self.create_menu(
            ConsoleWidgetMenus.InternalSettings,
            _('Internal console settings'),
            icon=self.create_icon('tooloptions'),
        )
        for item in [buffer_action, wrap_action, codecompletion_action,
                     exteditor_action]:
            self.add_item_to_menu(
                item,
                menu=internal_settings_menu,
                section=ConsoleWidgetInternalSettingsSubMenuSections.Main,
            )

        # Options menu
        options_menu = self.get_options_menu()
        for item in [run_action, environ_action, syspath_action,
                     internal_settings_menu]:
            self.add_item_to_menu(
                item,
                menu=options_menu,
                section=ConsoleWidgetOptionsMenuSections.Run,
            )

        self.add_item_to_menu(
            self.quit_action,
            menu=options_menu,
            section=ConsoleWidgetOptionsMenuSections.Quit,
        )

        self.shell.set_external_editor(
            self.get_conf('external_editor/path'), '')

    @on_conf_change(option='max_line_count')
    def max_line_count_update(self, value):
        self.shell.setMaximumBlockCount(value)

    @on_conf_change(option='wrap')
    def wrap_mode_update(self, value):
        self.shell.toggle_wrap_mode(value)

    @on_conf_change(option='external_editor/path')
    def external_editor_update(self, value):
        self.shell.set_external_editor(value, '')

    def update_actions(self):
        pass

    def get_focus_widget(self):
        return self.shell

    # --- Qt overrides
    # ------------------------------------------------------------------------
    def dragEnterEvent(self, event):
        """
        Reimplement Qt method.

        Inform Qt about the types of data that the widget accepts.
        """
        source = event.mimeData()
        if source.hasUrls():
            if mimedata2url(source):
                event.acceptProposedAction()
            else:
                event.ignore()
        elif source.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """
        Reimplement Qt method.

        Unpack dropped data and handle it.
        """
        source = event.mimeData()
        if source.hasUrls():
            pathlist = mimedata2url(source)
            self.shell.drop_pathlist(pathlist)
        elif source.hasText():
            lines = to_text_string(source.text())
            self.shell.set_cursor_position('eof')
            self.shell.execute_lines(lines)

        event.acceptProposedAction()

    # --- Public API
    # ------------------------------------------------------------------------
    def start_interpreter(self, namespace):
        """
        Start internal console interpreter.
        """
        self.shell.start_interpreter(namespace)

    def set_historylog(self, historylog):
        """
        Bind historylog instance to this console.

        Not used anymore since v2.0.
        """
        historylog.add_history(self.shell.history_filename)
        self.shell.sig_append_to_history_requested.connect(
            historylog.append_to_history)

    def set_help(self, help_plugin):
        """
        Bind help instance to this console.
        """
        self.shell.help = help_plugin

    def report_issue(self):
        """Report an issue with the SpyderErrorDialog."""
        self._report_dlg = SpyderErrorDialog(self, is_report=True)
        self._report_dlg.set_color_scheme(self.get_conf(
            'selected', section='appearance'))
        self._report_dlg.show()

    @Slot(dict)
    def handle_exception(self, error_data, sender=None):
        """
        Exception occurred in the internal console.

        Show a QDialog or the internal console to warn the user.

        Handle any exception that occurs during Spyder usage.

        Parameters
        ----------
        error_data: dict
            The dictionary containing error data. The expected keys are:
            >>> error_data= {
                "text": str,
                "is_traceback": bool,
                "repo": str,
                "title": str,
                "label": str,
                "steps": str,
            }
        sender: spyder.api.plugins.SpyderPluginV2, optional
            The sender plugin. Default is None.

        Notes
        -----
        The `is_traceback` key indicates if `text` contains plain text or a
        Python error traceback.

        The `title` and `repo` keys indicate how the error data should
        customize the report dialog and Github error submission.

        The `label` and `steps` keys allow customizing the content of the
        error dialog.
        """
        text = error_data.get("text", None)
        is_traceback = error_data.get("is_traceback", False)
        title = error_data.get("title", "")
        label = error_data.get("label", "")
        steps = error_data.get("steps", "")

        # Skip errors without traceback (and no text) or dismiss
        if ((not text and not is_traceback and self.error_dlg is None)
                or self.dismiss_error):
            return

        InstallerInternalError(title + text)

        # Retrieve internal plugins
        internal_plugins = PLUGIN_REGISTRY.internal_plugins

        # Get if sender is internal or not
        is_internal_plugin = True
        if sender is not None:
            sender_name = getattr(
                sender, 'NAME', getattr(sender, 'CONF_SECTION'))
            is_internal_plugin = sender_name in internal_plugins

        # Set repo
        repo = "spyder-ide/spyder"
        if not is_internal_plugin:
            repo = error_data.get("repo", None)

            if repo is None:
                raise SpyderAPIError(
                    f"External plugin '{sender_name}' does not define 'repo' "
                    "key in the 'error_data' dictionary in the form "
                    "my-org/my-repo (only Github is supported)."
                )

            if repo == 'spyder-ide/spyder':
                raise SpyderAPIError(
                    f"External plugin '{sender_name}' 'repo' key needs to be "
                    "different from the main Spyder repo."
                )

        if self.get_conf('show_internal_errors', section='main'):
            if self.error_dlg is None:
                self.error_dlg = SpyderErrorDialog(self)
                self.error_dlg.set_color_scheme(
                    self.get_conf('selected', section='appearance'))
                self.error_dlg.rejected.connect(self.remove_error_dlg)
                self.error_dlg.details.sig_go_to_error_requested.connect(
                    self.go_to_error)

            # Set the report repository
            self.error_dlg.set_github_repo_org(repo)

            if title:
                self.error_dlg.set_title(title)
                self.error_dlg.title.setEnabled(False)

            if label:
                self.error_dlg.main_label.setText(label)
                self.error_dlg.submit_btn.setEnabled(True)

            if steps:
                self.error_dlg.steps_text.setText(steps)
                self.error_dlg.set_require_minimum_length(False)

            self.error_dlg.append_traceback(text)
            self.error_dlg.show()
        elif DEV or get_debug_level():
            self.change_visibility(True, True)

    def close_error_dlg(self):
        """
        Close error dialog.
        """
        if self.error_dlg:
            self.error_dlg.reject()

    def remove_error_dlg(self):
        """
        Remove error dialog.
        """
        if self.error_dlg.dismiss_box.isChecked():
            self.dismiss_error = True

        if PYSIDE2 or PYSIDE6:
            self.error_dlg.disconnect(None, None, None)
        else:
            self.error_dlg.disconnect()
        self.error_dlg = None

    @Slot()
    def show_env(self):
        """
        Show environment variables.
        """
        self.dialog_manager.show(EnvDialog(parent=self))

    def get_sys_path(self):
        """
        Return the `sys.path`.
        """
        return sys.path

    @Slot()
    def show_syspath(self):
        """
        Show `sys.path`.
        """
        editor = CollectionsEditor(parent=self)
        editor.setup(
            sys.path,
            title="sys.path",
            readonly=True,
            icon=self.create_icon('syspath'),
        )
        self.dialog_manager.show(editor)

    @Slot()
    def run_script(self, filename=None, silent=False, args=None):
        """
        Run a Python script.
        """
        if filename is None:
            self.shell.interpreter.restore_stds()
            filename, _selfilter = getopenfilename(
                self,
                _("Run Python file"),
                getcwd_or_home(),
                _("Python files") + " (*.py ; *.pyw ; *.ipy)",
            )
            self.shell.interpreter.redirect_stds()

            if filename:
                os.chdir(osp.dirname(filename))
                filename = osp.basename(filename)
            else:
                return

        logger.debug("Running script with %s", args)
        filename = osp.abspath(filename)
        rbs = remove_backslashes
        command = '%runfile {} --args {}'.format(
            repr(rbs(filename)), repr(rbs(args)))

        self.change_visibility(True, True)

        self.shell.write(command+'\n')
        self.shell.run_command(command)

    def go_to_error(self, text):
        """
        Go to error if relevant.
        """
        match = get_error_match(to_text_string(text))
        if match:
            fname, lnb = match.groups()
            self.edit_script(fname, int(lnb))

    def edit_script(self, filename=None, goto=-1):
        """
        Edit script.
        """
        if filename is not None:
            # Called from InternalShell
            self.shell.external_editor(filename, goto)
            self.sig_edit_goto_requested.emit(osp.abspath(filename), goto, '')

    def execute_lines(self, lines):
        """
        Execute lines and give focus to shell.
        """
        self.shell.execute_lines(to_text_string(lines))
        self.shell.setFocus()

    @Slot()
    def change_max_line_count(self, value=None):
        """"
        Change maximum line count.
        """
        valid = True
        if value is None:
            value, valid = QInputDialog.getInt(
                self,
                _('Buffer'),
                _('Maximum line count'),
                self.get_conf('max_line_count'),
                0,
                1000000,
            )

        if valid:
            self.set_conf('max_line_count', value)

    @Slot()
    def change_exteditor(self, path=None):
        """
        Change external editor path.
        """
        valid = True
        if path is None:
            path, valid = QInputDialog.getText(
                self,
                _('External editor'),
                _('External editor executable path:'),
                QLineEdit.Normal,
                self.get_conf('external_editor/path'),
            )

        if valid:
            self.set_conf('external_editor/path', to_text_string(path))

    def set_exit_function(self, func):
        """
        Set the callback function to execute when the `exit_interpreter` is
        called.
        """
        self.shell.exitfunc = func

    def set_font(self, font):
        """
        Set font of the internal shell.
        """
        self.shell.set_font(font)

    def redirect_stds(self):
        """
        Redirect stdout and stderr when using open file dialogs.
        """
        self.shell.interpreter.redirect_stds()

    def restore_stds(self):
        """
        Restore stdout and stderr when using open file dialogs.
        """
        self.shell.interpreter.restore_stds()

    def set_namespace_item(self, name, item):
        """
        Add an object to the namespace dictionary of the internal console.
        """
        self.shell.interpreter.namespace[name] = item

    def exit_interpreter(self):
        """
        Exit the internal console interpreter.

        This is equivalent to requesting the main application to quit.
        """
        self.shell.exit_interpreter()
