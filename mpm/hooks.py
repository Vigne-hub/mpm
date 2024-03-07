import logging
import os
import subprocess as sp
import sys

import path_helpers as ph


logger = logging.getLogger(__name__)


def on_plugin_install(plugin_directory, ostream=sys.stdout):
    """
    Run ``on_plugin_install`` script for specified plugin directory (if
    available).

    **TODO** Add support for Linux, OSX.

    Parameters
    ----------
    plugin_directory : str
        File system to plugin directory.
    ostream :file-like
        Output stream for status messages (default: ``sys.stdout``).
    """
    current_directory = os.getcwd()

    plugin_directory = ph.path(plugin_directory)
    print(f'Processing post-install hook for: {plugin_directory.name}', file=ostream)

    hooks_dir_i = plugin_directory.joinpath('hooks/Windows').realpath()
    hook_path_i = hooks_dir_i.joinpath('on_plugin_install.bat')

    if hook_path_i.is_file():
        logger.info('Processing post-install hook for: %s',
                    plugin_directory.name)
        os.chdir(hook_path_i.parent)
        try:
            process = sp.Popen([hook_path_i, sys.executable], shell=True,
                               stdin=sp.PIPE)
            # Emulate return key press in case plugin uses
            # "Press <enter> key to continue..." prompt.
            process.communicate(input='\r\n'.encode())
            if process.returncode != 0:
                raise RuntimeError(f'Process return code == {process.returncode}')
            return hook_path_i
        except Exception as exception:
            raise RuntimeError(f'Error running: {hook_path_i}\n{exception}')
        finally:
            os.chdir(current_directory)
