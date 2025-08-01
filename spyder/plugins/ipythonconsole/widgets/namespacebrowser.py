# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
Widget that handle communications between the IPython Console and
the Variable Explorer
"""

# Standard library imports
import logging
from pickle import PicklingError, UnpicklingError
import sys

# Third-party imports
import cloudpickle
from packaging.version import parse
from qtconsole.rich_jupyter_widget import RichJupyterWidget
from spyder_kernels.comms.commbase import CommError

# Local imports
from spyder.config.base import _, is_conda_based_app

# For logging
logger = logging.getLogger(__name__)

# Max time before giving up when making a blocking call to the kernel
CALL_KERNEL_TIMEOUT = 30

# URL to our Github issues
GH_ISSUES = "https://github.com/spyder-ide/spyder/issues/new"


class NamepaceBrowserWidget(RichJupyterWidget):
    """
    Widget with the necessary attributes and methods to handle communications
    between the IPython Console and the kernel namespace
    """
    # --- Public API --------------------------------------------------
    def get_value(self, name):
        """Ask kernel for a value"""
        reason_big = _("The variable is too big to be retrieved")
        reason_not_picklable = _(
            "It was not possible to create a copy of the variable in the "
            "kernel or to load that copy in Spyder.<br><br>"
            "If the object you're trying to view contains a generator, you "
            "need to replace it by a list because generators can't be "
            "serialized."
        )
        reason_dead = _("The kernel is dead")
        reason_other = _("An unknown error occurred, sorry.")
        reason_comm = _(
            "The channel used to communicate with the kernel is not working."
        )
        reason_missing_package_target = _(
            "The '<tt>{}</tt>' module is required to open this variable and "
            "it's not installed in the console environment. To fix this "
            "problem, please install it in the environment which you use to "
            "run your code."
        )
        reason_missing_package_installer = _(
            "The '<tt>{}</tt>' module is required to open this variable. "
            "Unfortunately, it's not part of our installer, which means your "
            "variable can't be displayed by Spyder."
        )
        reason_missing_package = _(
            "The '<tt>{}</tt>' module is required to open this variable and "
            "it's not installed alongside Spyder. To fix this problem, please "
            "install it in the same environment that you use to run Spyder."
        )
        reason_mismatched_numpy = _(
            "There is a mismatch between the Numpy versions used by Spyder "
            "and the kernel of your current console. To fix this problem, "
            "please upgrade <tt>numpy</tt> in the environment that you use to "
            "run Spyder to version 1.26.1 or higher."
        )
        reason_mismatched_pandas = _(
            "There is a mismatch between the Pandas versions used by Spyder "
            "and the kernel of your current console. To fix this problem, "
            "please upgrade <tt>pandas</tt> in the console environment "
            "to version 2.0 or higher."
        )
        reason_mismatched_python = _(
            "There is a mismatch between the Python versions used by Spyder "
            "({}) and the kernel of your current console ({}).<br><br>"
            "To fix it, you need to recreate your console environment with "
            "Python {} or {}."
        )

        msg = _(
            "<br>%s<br><br>"
            "<b>Note</b>: If you consider this to be a valid error that needs "
            "to be fixed by the Spyder team, please report it on "
            "<a href='{}'>Github</a>."
        ).format(GH_ISSUES)

        kernel_call_success = False
        try:
            value = self.call_kernel(
                blocking=True,
                # We prefer not to display errors because it's not clear that
                # they are related to what users are doing in the Variable
                # Explorer. So, it's not user friendly.
                # See spyder-ide/spyder#22411
                display_error=False,
                timeout=CALL_KERNEL_TIMEOUT
            ).get_value(name, encoded=True)
            kernel_call_success = True
            value = cloudpickle.loads(value)
            return value
        except TimeoutError:
            raise ValueError(msg % reason_big)
        except (PicklingError, UnpicklingError, TypeError) as err:
            if str(err).startswith(
                ("code expected at most", "code() argument")
            ):
                # This error happens when Spyder is using Python 3.11+ and the
                # kernel 3.10-, or the other way around. In that case,
                # cloudpickle can't deserialize the objects sent from the
                # kernel and we need to inform users about it.
                # Fixes spyder-ide/spyder#24125.
                py_spyder_version = ".".join(
                    [str(n) for n in sys.version_info[:3]]
                )
                py_kernel_version = self.get_pythonenv_info()["python_version"]

                if parse(py_spyder_version) < parse(py_kernel_version):
                    py_good_version, compatible_versions  = "3.10", _("lower")
                else:
                    py_good_version, compatible_versions = "3.11", _("greater")

                raise ValueError(
                    msg
                    % reason_mismatched_python.format(
                        py_spyder_version,
                        py_kernel_version,
                        py_good_version,
                        compatible_versions,
                    )
                )

            raise ValueError(msg % reason_not_picklable)
        except RuntimeError:
            raise ValueError(msg % reason_dead)
        except KeyError:
            raise
        except CommError:
            raise ValueError(msg % reason_comm)
        except ModuleNotFoundError as e:
            if not kernel_call_success:
                name = e.args[0].error.name
                reason = reason_missing_package_target.format(name)
            elif is_conda_based_app():
                reason = reason_missing_package_installer.format(e.name)
            elif e.name.startswith('numpy._core'):
                reason = reason_mismatched_numpy
            elif e.name == 'pandas.core.indexes.numeric':
                reason = reason_mismatched_pandas
            else:
                reason = reason_missing_package.format(e.name)
            raise ValueError(msg % reason)
        except Exception:
            raise ValueError(msg % reason_other)

    def set_value(self, name, value):
        """Set value for a variable"""
        reason_mismatched_numpy = _(
            "There is a mismatch between the Numpy versions used by Spyder "
            "and the kernel of your current console. To fix this problem, "
            "please upgrade <tt>numpy</tt> in the console environment to "
            "version 2.0 or higher."
        )
        msg = _(
            "<br>%s<br><br>"
            "<b>Note</b>: If you consider this to be a valid error that needs "
            "to be fixed by the Spyder team, please report it on "
            "<a href='{}'>Github</a>."
        ).format(GH_ISSUES)

        # Encode with cloudpickle and base64
        encoded_value = cloudpickle.dumps(value)

        try:
            self.call_kernel(
                interrupt=True,
                blocking=True,
                display_error=True,
            ).set_value(name, encoded_value, encoded=True)
        except ModuleNotFoundError as e:
            name = e.args[0].error.name
            if name.startswith('numpy._core'):
                raise ValueError(msg % reason_mismatched_numpy)
        except Exception:
            pass  # swallow exception

    def remove_value(self, name):
        """Remove a variable"""
        self.call_kernel(
            interrupt=True,
            blocking=False,
            display_error=True,
            ).remove_value(name)

    def copy_value(self, orig_name, new_name):
        """Copy a variable"""
        self.call_kernel(
            interrupt=True,
            blocking=False,
            display_error=True,
            ).copy_value(orig_name, new_name)
