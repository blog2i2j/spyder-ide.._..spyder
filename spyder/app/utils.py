# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""Utility functions for the Spyder application."""

# Standard library imports
import glob
import logging
import os
import os.path as osp
import re
import sys

# Third-party imports
import psutil
from qtpy.QtCore import QCoreApplication, Qt
from qtpy.QtGui import QColor, QIcon, QPalette, QPixmap, QPainter, QImage
from qtpy.QtWidgets import QSplashScreen
from qtpy.QtSvg import QSvgRenderer

# Local imports
from spyder.config.base import (
    get_conf_path,
    get_debug_level,
    is_conda_based_app,
    running_under_pytest,
)
from spyder.config.manager import CONF
from spyder.utils.external.dafsa.dafsa import DAFSA
from spyder.utils.image_path_manager import get_image_path
from spyder.utils.installers import running_installer_test
from spyder.utils.palette import SpyderPalette
from spyder.utils.qthelpers import file_uri, qapplication

# For spyder-ide/spyder#7447.
try:
    from qtpy.QtQuick import QQuickWindow, QSGRendererInterface
except Exception:
    QQuickWindow = QSGRendererInterface = None


root_logger = logging.getLogger()
FILTER_NAMES = os.environ.get('SPYDER_FILTER_LOG', "").split(',')
FILTER_NAMES = [f.strip() for f in FILTER_NAMES]

# Keeping a reference to the original sys.exit before patching it
ORIGINAL_SYS_EXIT = sys.exit


class Spy:
    """
    This is used to inject a 'spy' object in the internal console
    namespace to inspect Spyder internals.

    Attributes:
        app       Reference to main QApplication object
        window    Reference to spyder.MainWindow widget
    """
    def __init__(self, app, window):
        self.app = app
        self.window = window

    def __dir__(self):
        return (list(self.__dict__.keys()) +
                [x for x in dir(self.__class__) if x[0] != '_'])


def get_python_doc_path():
    """
    Return Python documentation path
    (Windows: return the PythonXX.chm path if available)
    """
    if os.name == 'nt':
        doc_path = osp.join(sys.prefix, "Doc")
        if not osp.isdir(doc_path):
            return
        python_chm = [path for path in os.listdir(doc_path)
                      if re.match(r"(?i)Python[0-9]{3,6}.chm", path)]
        if python_chm:
            return file_uri(osp.join(doc_path, python_chm[0]))
    else:
        vinf = sys.version_info
        doc_path = '/usr/share/doc/python%d.%d/html' % (vinf[0], vinf[1])
    python_doc = osp.join(doc_path, "index.html")
    if osp.isfile(python_doc):
        return file_uri(python_doc)


def set_opengl_implementation(option):
    """
    Set the OpenGL implementation used by Spyder.

    See spyder-ide/spyder#7447 for the details.
    """
    if hasattr(QQuickWindow, "setGraphicsApi"):
        set_api = QQuickWindow.setGraphicsApi  # Qt 6
    else:
        if QQuickWindow is not None:
            set_api = QQuickWindow.setSceneGraphBackend  # Qt 5

    if option == 'software':
        QCoreApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
        if QQuickWindow is not None:
            set_api(QSGRendererInterface.GraphicsApi.Software)
    elif option == 'desktop':
        QCoreApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
        if QQuickWindow is not None:
            set_api(QSGRendererInterface.GraphicsApi.OpenGL)
    elif option == 'gles':
        QCoreApplication.setAttribute(Qt.AA_UseOpenGLES)
        if QQuickWindow is not None:
            set_api(QSGRendererInterface.GraphicsApi.OpenGL)


def setup_logging(cli_options):
    """Setup logging with cli options defined by the user."""
    if cli_options.debug_info or get_debug_level() > 0:
        levels = {2: logging.INFO, 3: logging.DEBUG}
        log_level = levels[get_debug_level()]
        log_format = '%(asctime)s [%(levelname)s] [%(name)s] -> %(message)s'

        console_filters = cli_options.filter_log.split(',')
        console_filters = [x.strip() for x in console_filters]
        console_filters = console_filters + FILTER_NAMES
        console_filters = [x for x in console_filters if x != '']

        handlers = [logging.StreamHandler()]
        filepath = os.environ['SPYDER_DEBUG_FILE']
        handlers.append(
            logging.FileHandler(filename=filepath, mode='w+')
        )

        match_func = lambda x: True
        if console_filters != [''] and len(console_filters) > 0:
            dafsa = DAFSA(console_filters)
            match_func = lambda x: (dafsa.lookup(x, stop_on_prefix=True)
                                    is not None)

        formatter = logging.Formatter(log_format)

        class ModuleFilter(logging.Filter):
            """Filter messages based on module name prefix."""

            def filter(self, record):
                return match_func(record.name)

        filter = ModuleFilter()
        root_logger.setLevel(log_level)
        for handler in handlers:
            handler.addFilter(filter)
            handler.setFormatter(formatter)
            handler.setLevel(log_level)
            root_logger.addHandler(handler)


def delete_debug_log_files():
    """Delete previous debug log files."""
    regex = re.compile(r'.*_.*_(\d+)[.]log')
    files = glob.glob(osp.join(get_conf_path('lsp_logs'), '*.log'))
    for f in files:
        match = regex.match(f)
        if match is not None:
            pid = int(match.group(1))
            if not psutil.pid_exists(pid):
                os.remove(f)

    debug_file = os.environ['SPYDER_DEBUG_FILE']
    if osp.exists(debug_file):
        os.remove(debug_file)


def qt_message_handler(msg_type, msg_log_context, msg_string):
    """
    Qt warning messages are intercepted by this handler.

    On some operating systems, warning messages might be displayed
    even if the actual message does not apply. This filter adds a
    blacklist for messages that are unnecessary. Anything else will
    get printed in the internal console.
    """
    BLACKLIST = [
        'QMainWidget::resizeDocks: all sizes need to be larger than 0',
        # This is shown at startup due to our splash screen but it's harmless
        "fromIccProfile: failed minimal tag size sanity",
        # This is shown when expanding/collpasing folders in the Files plugin
        # after spyder-ide/spyder#
        "QFont::setPixelSize: Pixel size <= 0 (0)",
        # These warnings are shown uncollapsing CollapsibleWidget
        "QPainter::begin: Paint device returned engine == 0, type: 2",
        "QPainter::save: Painter not active",
        "QPainter::setPen: Painter not active",
        "QPainter::setWorldTransform: Painter not active",
        "QPainter::setOpacity: Painter not active",
        "QFont::setPixelSize: Pixel size <= 0 (-3)",
        "QPainter::setFont: Painter not active",
        "QPainter::restore: Unbalanced save/restore",
        # This warning is shown at startup when using PyQt6
        "<use> element image0 in wrong context!",
    ]
    if msg_string not in BLACKLIST:
        print(msg_string)  # spyder: test-skip


def create_splash_screen(use_previous_factor=False):
    """
    Create splash screen.

    Parameters
    ----------
    use_previous_factor: bool, optional
        Use previous scale factor when creating the splash screen. This is used
        when restarting Spyder, so the screen looks as expected. Default is
        False.
    """
    if not running_under_pytest():
        # This is a good size for the splash screen image at a scale factor of
        # 1. It corresponds to 75 ppi and preserves its aspect ratio.
        width = 526
        height = 432

        # This allows us to use the previous scale factor for the splash screen
        # shown when Spyder is restarted. Otherwise, it appears pixelated.
        previous_factor = float(
            CONF.get('main', 'prev_high_dpi_custom_scale_factors', 1)
        )

        # We need to increase the image size according to the scale factor to
        # be displayed correctly.
        # See https://falsinsoft.blogspot.com/2016/04/
        # qt-snippet-render-svg-to-qpixmap-for.html for details.
        if CONF.get('main', 'high_dpi_custom_scale_factor'):
            if not use_previous_factor:
                factors = CONF.get('main', 'high_dpi_custom_scale_factors')
                factor = float(factors.split(":")[0])
            else:
                factor = previous_factor
        else:
            if not use_previous_factor:
                factor = 1
            else:
                factor = previous_factor

        # Save scale factor for restarts.
        CONF.set('main', 'prev_high_dpi_custom_scale_factors', factor)

        image = QImage(
            int(width * factor), int(height * factor),
            QImage.Format_ARGB32_Premultiplied
        )
        image.fill(0)
        painter = QPainter(image)
        renderer = QSvgRenderer(get_image_path('splash'))
        renderer.render(painter)
        painter.end()

        # This is also necessary to make the image look good.
        if factor > 1.0:
            image.setDevicePixelRatio(factor)

        pm = QPixmap.fromImage(image)
        pm = pm.copy(0, 0, int(width * factor), int(height * factor))

        splash = QSplashScreen(pm)
    else:
        splash = None

    return splash


def set_links_color(app):
    """
    Fix color for links.

    This was taken from QDarkstyle, which is MIT licensed.
    """
    color = SpyderPalette.COLOR_ACCENT_4
    qcolor = QColor(color)

    app_palette = app.palette()
    app_palette.setColor(QPalette.Normal, QPalette.Link, qcolor)
    app.setPalette(app_palette)


def create_application():
    """Create application and patch sys.exit."""
    # Our QApplication
    app = qapplication()

    # ---- Set icon
    app_icon = QIcon(get_image_path("spyder"))
    app.setWindowIcon(app_icon)

    # ---- Set font
    # The try/except is necessary to run the main window tests on their own.
    try:
        app.set_font()
    except AttributeError as error:
        if running_under_pytest():
            # Set font options to avoid a ton of Qt warnings when running tests
            app_family = app.font().family()
            app_size = app.font().pointSize()
            CONF.set('appearance', 'app_font/family', app_family)
            CONF.set('appearance', 'app_font/size', app_size)

            from spyder.config.fonts import MEDIUM, MONOSPACE
            CONF.set('appearance', 'monospace_app_font/family', MONOSPACE[0])
            CONF.set('appearance', 'monospace_app_font/size', MEDIUM)
        else:
            # Raise in case the error is valid
            raise error

    # Required for correct icon on GNOME/Wayland:
    if hasattr(app, 'setDesktopFileName'):
        app.setDesktopFileName('spyder')

    # ---- Monkey patching sys.exit
    def fake_sys_exit(arg=[]):
        pass
    sys.exit = fake_sys_exit

    # ---- Monkey patching sys.excepthook to avoid crashes in PyQt 5.5+
    def spy_excepthook(type_, value, tback):
        sys.__excepthook__(type_, value, tback)
        if running_installer_test():
            # This will exit Spyder with exit code 1 without invoking
            # macOS system dialogue window.
            raise SystemExit(1)
    sys.excepthook = spy_excepthook

    # Removing arguments from sys.argv as in standard Python interpreter
    sys.argv = ['']

    return app


def create_window(WindowClass, app, splash, options, args):
    """
    Create and show Spyder's main window and start QApplication event loop.

    Parameters
    ----------
    WindowClass: QMainWindow
        Subclass to instantiate the Window.
    app: QApplication
        Instance to start the application.
    splash: QSplashScreen
        Splash screen instamce.
    options: argparse.Namespace
        Command line options passed to Spyder
    args: list
        List of file names passed to the Spyder executable in the
        command line.
    """
    # Main window
    main = WindowClass(splash, options)
    try:
        main.setup()
    except BaseException:
        if main.console is not None:
            try:
                main.console.exit_interpreter()
            except BaseException:
                pass
        raise

    main.pre_visible_setup()
    main.show()
    main.post_visible_setup()

    # Add a reference to the main window so it can be accessed from the
    # application.
    #
    # Notes
    # -----
    # * **DO NOT** use it to access other plugins functionality through it.
    app._main_window = main

    if main.console:
        main.console.start_interpreter(namespace={})
        main.console.set_namespace_item('spy', Spy(app=app, window=main))

    # Propagate current configurations to all configuration observers
    CONF.notify_all_observers()

    # Don't show icons in menus for Mac
    if sys.platform == 'darwin':
        QCoreApplication.setAttribute(Qt.AA_DontShowIconsInMenus, True)

    # Open external files with our Mac app
    # ??? Do we need this?
    if sys.platform == 'darwin' and is_conda_based_app():
        app.sig_open_external_file.connect(main.open_external_file)
        app._has_started = True
        if hasattr(app, '_pending_file_open'):
            if args:
                args = app._pending_file_open + args
            else:
                args = app._pending_file_open

    # Open external files passed as args
    if args:
        for a in args:
            main.open_external_file(a)

    # To give focus again to the last focused widget after restoring
    # the window
    app.focusChanged.connect(main.change_last_focused_widget)

    if not running_under_pytest():
        app.exec_()
    return main
