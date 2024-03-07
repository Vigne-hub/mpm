import logging
import os
import subprocess as sp
import sys

import path_helpers as ph


logger = logging.getLogger(__name__)


def on_plugin_install(plugin_directory, ostream=sys.stdout):
    '''
    Run ``on_plugin_install`` script for specified plugin directory (if
    available).

    **TODO** Add support for Linux, OSX.

    Parameters
    ----------
    plugin_directory : str
        File system to plugin directory.
    ostream :file-like
        Output stream for status messages (default: ``sys.stdout``).
    '''
    current_directory = os.getcwd()

    plugin_directory = ph.path(plugin_directory).realpath()
    print >> ostream, ('Processing post-install hook for: '
                        '{}'.format(plugin_directory.name))

    hooks_dir_i = plugin_directory.joinpath('hooks/Windows').realpath()
    hook_path_i = hooks_dir_i.joinpath('on_plugin_install.bat')

    if hook_path_i.isfile():
        logger.info('Processing post-install hook for: %s',
                    plugin_directory.name)
        os.chdir(hook_path_i.parent)
        try:
            process = sp.Popen([hook_path_i, sys.executable], shell=True,
                               stdin=sp.PIPE)
            # Emulate return key press in case plugin uses
            # "Press <enter> key to continue..." prompt.
            process.communicate(input='\r\n')
            if process.returncode != 0:
                raise RuntimeError('Process return code == {}'
                                   .format(process.returncode))
            return hook_path_i
        except Exception as exception:
            raise RuntimeError('Error running: {}\n{}'.format(hook_path_i,
                                                              exception))
        finally:
            os.chdir(current_directory)
