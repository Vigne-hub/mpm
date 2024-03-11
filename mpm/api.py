# coding: utf-8
'''
See https://github.com/wheeler-microfluidics/microdrop/issues/216
'''
import bz2
import importlib
import logging
import json
import platform
import re
import sys
import conda_helpers as ch
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

MICRODROP_CONDA_ETC = ch.conda_prefix().joinpath('etc', 'microdrop')
MICRODROP_CONDA_SHARE = ch.conda_prefix().joinpath('share', 'microdrop')
MICRODROP_CONDA_ACTIONS = MICRODROP_CONDA_ETC.joinpath('actions')
MICRODROP_CONDA_PLUGINS = MICRODROP_CONDA_ETC.joinpath('plugins')

__all__ = ['available_packages', 'install', 'rollback', 'uninstall',
           'enable_plugin', 'disable_plugin', 'update', 'MICRODROP_CONDA_ETC',
           'MICRODROP_CONDA_SHARE', 'MICRODROP_CONDA_ACTIONS',
           'MICRODROP_CONDA_PLUGINS']


def _islinklike(dir_path):
    """
    Parameters
    ----------
    dir_path : str
        Directory path.

    Returns
    -------
    bool
        ``True`` if :data:`dir_path` is a link *or* junction.
    """
    dir_path = Path(dir_path)
    if platform.system() == 'Windows':
        if dir_path.is_symlink():
            return True
    elif dir_path.is_symlink():
        return True
    return False


def _save_action(extra_context=None):
    """
    Save list of revisions revisions for active Conda environment.

    .. versionchanged:: 0.18
        Compress action revision files using ``bz2`` to save disk space.

    Parameters
    ----------
    extra_context : dict, optional
        Extra content to store in stored action revision.

    Returns
    -------
    pathlib.Path, dict
        Path to which action was written and action object, including list of
        revisions for active Conda environment.
    """
    # Get list of revisions to Conda environment since creation.
    revisions_js = ch.conda_exec('list', '--revisions', '--json', verbose=False)
    revisions = json.loads(revisions_js)
    # Save list of revisions to `/etc/microdrop/plugins/actions/rev<rev>.json`
    # See [wheeler-microfluidics/microdrop#200][i200].
    #
    # [i200]: https://github.com/wheeler-microfluidics/microdrop/issues/200
    action = extra_context.copy() if extra_context else {}
    action['revisions'] = revisions
    action_path = MICRODROP_CONDA_ACTIONS / f'rev{revisions[-1]["rev"]}.json.bz2'
    action_path.parent.mkdir(parents=True, exist_ok=True)
    # Compress action file using bz2 to save disk space.
    with bz2.open(action_path, mode='wt', compresslevel=9) as output:
        json.dump(action, output, indent=2)

    return action_path, action


def _remove_broken_links():
    """
    Remove broken links in `<conda prefix>/etc/microdrop/plugins/enabled/`.

    Returns
    -------
    list
        List of links removed (if any).
    """
    enabled_dir = MICRODROP_CONDA_PLUGINS / 'enabled'
    if not enabled_dir.is_dir():
        return []

    def is_broken_link(path):
        """
        Checks if the given path is a broken symlink or junction.
        """
        if platform.system() == 'Windows':
            # On Windows, is_symlink() also returns True for junctions
            return path.is_symlink() and not path.exists()
        else:
            # currently do not support non windows
            raise NotImplementedError('Unsupported platform')

    broken_links = [dir_i for dir_i in enabled_dir.glob('**/*') if is_broken_link(dir_i)]

    removed_links = []
    for link_i in broken_links:
        try:
            link_i.unlink()
            removed_links.append(link_i)
        except Exception as e:
            # Optionally log the error or pass
            print(f"Error removing link {link_i}: {e}")
            # pass
    return removed_links


# ## Supporting legacy MicroDrop plugins ##
#
# Legacy MicroDrop plugins **MAY** be made **available** by linking according
# to **(2)** above.
#
# # TODO #
#
#  - [ ] Create Python API for MicroDrop plugins to:
#      * [x] Query available plugin packages based on specified Conda channels
def available_packages(*args, **kwargs):
    """
    Query available plugin packages based on specified Conda channels.

    Parameters
    ----------
    *args
        Extra arguments to pass to Conda ``search`` command.

    Returns
    -------
    dict
        .. versionchanged:: 0.24
            All Conda packages beginning with ``microdrop.`` prefix from all
            configured channels.

        Each *key* corresponds to a package name.

        Each *value* corresponds to a ``list`` of dictionaries, each
        corresponding to an available version of the respective package.

        For example:

            {
              "microdrop.dmf-device-ui-plugin": [
                ...
                {
                  ...
                  "build_number": 0,
                  "channel": "microdrop-plugins",
                  "installed": true,
                  "license": "BSD",
                  "name": "microdrop.dmf-device-ui-plugin",
                  "size": 62973,
                  "version": "2.1.post2",
                  ...
                },
                ...],
                ...
            }
    """
    # Get list of available MicroDrop plugins, i.e., Conda packages that start
    # with the prefix `microdrop.`.
    try:
        plugin_packages_info_json = ch.conda_exec('search', '--json',
                                                  '^microdrop\.', *args, **kwargs, verbose=False)
        return json.loads(plugin_packages_info_json)
    except RuntimeError as exception:
        if 'CondaHTTPError' in str(exception):
            logger.warning('Could not connect to Conda server.')
        else:
            logger.warning('Error querying available MicroDrop plugins.',
                           exc_info=True)
    except Exception as exception:
        logger.warning('Error querying available MicroDrop plugins.',
                       exc_info=True)
    return {}


#      * [x] Install plugin package(s) from selected Conda channels
def install(plugin_name, *args, **kwargs):
    """
    Install plugin packages based on specified Conda channels.

    .. versionchanged:: 0.19.1
        Do not save rollback info on dry-run.

    .. versionchanged:: 0.24
        Remove channels argument.  Use Conda channels as configured in Conda
        environment.

        Note that channels can still be explicitly set through :data:`*args`.

    Parameters
    ----------
    plugin_name : str or list
        Plugin package(s) to install.

        Version specifiers are also supported, e.g., ``package >=1.0.5``.
    *args
        Extra arguments to pass to Conda ``install`` command.

    Returns
    -------
    dict
        Conda installation log object (from JSON Conda install output).
    """
    # Ensure plugin_name is a list to simplify processing
    plugin_names = [plugin_name] if isinstance(plugin_name, str) else plugin_name

    # Prepare Conda command arguments
    conda_args = ['install', '-y', '--json'] + list(args) + plugin_names
    install_log_js = ch.conda_exec(*conda_args, **kwargs, verbose=False)
    install_log = json.loads(install_log_js.split('\x00')[-1])

    # Check for actual installation actions and if not a dry-run
    if 'actions' in install_log and not install_log.get('dry_run'):

        # Install command modified Conda environment. Save the action for potential rollback.
        _save_action({'conda_args': conda_args, 'install_log': install_log})
        logger.debug('Installed plugin(s): %s', install_log['actions'])

    return install_log


#      * [x] **Rollback** (i.e., load last revision number from latest
#        `<conda prefix>/etc/microdrop/plugins/restore_points/r<revision>.json`
#        and run `conda install --revision <revision number>`), see #200
def rollback(*args, **kwargs):
    """
    Restore previous revision of Conda environment according to most recent
    action in :attr:`MICRODROP_CONDA_ACTIONS`.

    .. versionchanged:: 0.18
        Add support for action revision files compressed using ``bz2``.

    .. versionchanged:: 0.24
        Remove channels argument.  Use Conda channels as configured in Conda
        environment.

        Note that channels can still be explicitly set through :data:`*args`.

    Parameters
    ----------
    *args
        Extra arguments to pass to Conda ``install`` roll-back command.

    Returns
    -------
    int, dict
        Revision after roll back and Conda installation log object (from JSON
        Conda install output).

    See also
    --------

    `wheeler-microfluidics/microdrop#200 <https://github.com/wheeler-microfluidics/microdrop/issues/200>`
    """
    action_files = list(MICRODROP_CONDA_ACTIONS.glob('*'))
    if not action_files:
        # No action files, return current revision.
        logger.debug('No rollback actions have been recorded.')
        revisions_js = ch.conda_exec('list', '--revisions', '--json',
                                     verbose=False)
        revisions = json.loads(revisions_js)
        return revisions[-1]['rev']

    # Compiling regular expression to match revision files
    cre_rev = re.compile(r'rev(?P<rev>\d+)')
    # Sorting and selecting the most recent action file
    action_file = sorted([(int(cre_rev.match(file_i.stem).group('rev')), file_i)
                          for file_i in action_files
                          if cre_rev.match(file_i.stem)],
                         key=lambda x: x[0], reverse=True)[0][1]
    # Reading action information based on file extension
    if action_file.suffix.lower() == '.bz2':
        # File is compressed using bz2.
        with bz2.open(action_file, mode='rt') as input_:
            action = json.load(input_)
    else:
        # Assume it is raw JSON.
        with action_file.open('r') as input_:
            action = json.load(input_)

    rollback_revision = action['revisions'][-2]
    conda_args = (['install', '--json'] + list(args) +
                  ['--revision', str(rollback_revision)])
    install_log_js = ch.conda_exec(*conda_args, verbose=False)
    install_log = json.loads(install_log_js.split('\x00')[-1])
    logger.debug('Rolled back to revision %s', rollback_revision)
    return rollback_revision, install_log


#      * [x] Uninstall plugin package(s) from selected Conda channels
#          - Remove broken links in `<conda prefix>/etc/microdrop/plugins/enabled/`
def uninstall(plugin_name, *args):
    """
    Uninstall plugin packages.

    Plugin packages must have a directory with the same name as the package in
    the following directory:

        <conda prefix>/share/microdrop/plugins/available/

    Parameters
    ----------
    plugin_name : str or list
        Plugin package(s) to uninstall.
    *args
        Extra arguments to pass to Conda ``uninstall`` command.

    Returns
    -------
    dict
        Conda uninstallation log object (from JSON Conda uninstall output).
    """
    # Ensure plugin_name is a list for uniform processing
    plugin_names = [plugin_name] if isinstance(plugin_name, str) else plugin_name

    available_path = MICRODROP_CONDA_SHARE / 'plugins' / 'available'
    for name_i in plugin_names:
        plugin_module_i = name_i.split('.')[-1].replace('-', '_')
        plugin_path_i = available_path / plugin_module_i
        if not plugin_path_i.exists():
            raise IOError(f'Plugin `{name_i}` not found in `{available_path}`')
        else:
            logger.debug(f'[uninstall] Found plugin `{plugin_path_i}`')

    # Perform uninstall operation.
    conda_args = ['uninstall', '--json', '-y'] + list(args) + plugin_names
    uninstall_log_js = ch.conda_exec(*conda_args, verbose=False)
    # Remove broken links in `<conda prefix>/etc/microdrop/plugins/enabled/`,
    # since uninstall may have made one or more packages unavailable.
    _remove_broken_links()
    logger.debug(f'Uninstalled plugins: {plugin_names}')
    return json.loads(uninstall_log_js.split('\x00')[-1])


#      * [x] Enable/disable installed plugin package(s)
def enable_plugin(plugin_name):
    """
    Enable installed plugin package(s).

    Each plugin package must have a directory with the same name as the package
    in the following directory:

        <conda prefix>/share/microdrop/plugins/available/

    Parameters
    ----------
    plugin_name : str or list
        Plugin package(s) to enable.

    Returns
    -------
    dict
        Dictionary containing a flag for each plugin name:

         - ``False`` iff the plugin was already enabled.
         - ``True`` iff it was just enabled now.

    Raises
    ------
    IOError
        If plugin is not installed to ``<conda prefix>/share/microdrop/plugins/available/``.
    """
    if isinstance(plugin_name, str):
        plugin_names = [plugin_name]
    else:
        plugin_names = plugin_name

    # Conda-managed plugins
    shared_available_path = MICRODROP_CONDA_SHARE / 'plugins' / 'available'
    # User-managed plugins
    etc_available_path = MICRODROP_CONDA_ETC / 'plugins' / 'available'

    # Link all specified plugins in
    # `<conda prefix>/etc/microdrop/plugins/enabled/` (if not already linked).
    enabled_path = MICRODROP_CONDA_PLUGINS.joinpath('enabled')
    enabled_path.makedirs_p()

    # Set flag for each plugin: `False` iff the plugin was already enabled,
    # `True` iff it was just enabled now.
    enabled_now = {}

    for name in plugin_names:
        # Find plugin in available paths
        for available_path in (etc_available_path, shared_available_path):
            plugin_path = available_path / name
            if plugin_path.exists():
                break
        else:
            raise IOError(f'Plugin `{name}` not found in `{etc_available_path}` or `{shared_available_path}`')

        # Enable plugin if not already enabled
        link_path = enabled_path / name
        if not link_path.exists():
            # On Windows, create a junction; otherwise, create a symlink
            if platform.system() == 'Windows':
                # For Windows, using os.symlink might require elevated privileges for junctions
                # Consider using a specific Windows API or command line for junction creation if necessary
                raise NotImplementedError('Junction creation is not directly supported by this script on Windows.')
            else:
                plugin_path.symlink_to(link_path)
            logger.debug(f'Enabled plugin directory: `{plugin_path}` -> `{link_path}`')
            enabled_now[name] = True
        else:
            logger.debug(f'Plugin already enabled: `{plugin_path}` -> `{link_path}`')
            enabled_now[name] = False

    return enabled_now


def disable_plugin(plugin_name):
    """
    Disable plugin package(s).

    Parameters
    ----------
    plugin_name : str or list
        Plugin package(s) to disable.

    Raises
    ------
    IOError
        If plugin is not enabled.
    """
    plugin_names = [plugin_name] if isinstance(plugin_name, str) else plugin_name

    # Path to the directory where enabled plugins are linked
    enabled_path = MICRODROP_CONDA_PLUGINS / 'enabled'

    for name in plugin_names:
        plugin_link_path = enabled_path / name
        # Check if the plugin link exists and appears to be a symlink or directory
        if not plugin_link_path.exists():
            raise IOError(f'Plugin `{name}` not found in `{enabled_path}` or is not a symlink/junction.')

        # Remove the symlink or junction
        plugin_link_path.unlink()
        logger.debug(f'Disabled plugin `{name}` (i.e., removed `{plugin_link_path}`)')


def update(*args, **kwargs):
    """
    Update installed plugin package(s).

    Each plugin package must have a directory (**NOT** a link) containing a
    ``properties.yml`` file with a ``package_name`` value in the following
    directory:

        <conda prefix>/share/microdrop/plugins/available/

    Parameters
    ----------
    *args
        Extra arguments to pass to Conda ``install`` command.

        See :func:`install`.
    package_name : str or list, optional
        Name(s) of MicroDrop plugin Conda package(s) to update.

        By default, all installed packages are updated.
    **kwargs
        See :func:`install`.

    Returns
    -------
    dict
        Conda installation log object (from JSON ``conda install`` output).

    Notes
    -----
    Only actual plugin directories are considered when updating (i.e., **NOT**
    directory links).

    This permits, for example, linking of a plugin into the ``available``
    plugins directory during development without risking overwriting during an
    update.

    Raises
    ------
    RuntimeError
        If one or more installed plugin packages cannot be updated.

        This can happen, for example, if the plugin package is not available in
        any of the specified Conda channels.

    See also
    --------
    :func:`installed_plugins`
    """
    package_name = kwargs.pop('package_name', None)

    # Retrieve a list of all installed plugins that are managed by Conda
    installed_plugins_ = installed_plugins(only_conda=True)

    if installed_plugins_:
        plugin_packages = [plugin['package_name'] for plugin in installed_plugins_]
        if package_name is None:
            package_name = plugin_packages
        elif isinstance(package_name, str):
            package_name = [package_name]

        logger.info(f'Updating plugins: {", ".join(f"`{name}`" for name in package_name)}')

        # Attempt to install plugin packages.
        try:
            install_log = install(package_name, *args, **kwargs)
        except RuntimeError as exception:
            if 'CondaHTTPError' in str(exception):
                raise IOError('Error accessing update server.')
            else:
                raise
        if 'actions' in install_log:
            logger.debug(f'Updated plugin(s): {install_log["actions"]}')
        return install_log
    else:
        return {}


def import_plugin(package_name, include_available=False):
    """
    Import MicroDrop plugin.

    Parameters
    ----------
    package_name : str
        Name of MicroDrop plugin Conda package.
    include_available : bool, optional
        If ``True``, import from all available plugins (not just **enabled**
        ones).

        By default, only the ``<conda>/etc/microdrop/plugins/enabled``
        directory is added to the Python import paths (if necessary).

        If ``True``, also add the ``<conda>/share/microdrop/plugins/available``
        directory to the Python import paths.

    Returns
    -------
    module
        Imported plugin module.
    """
    available_plugins_dir = MICRODROP_CONDA_SHARE / 'plugins' / 'available'
    enabled_plugins_dir = MICRODROP_CONDA_ETC / 'plugins' / 'enabled'
    search_paths = [str(enabled_plugins_dir)]

    if include_available:
        search_paths.append(str(available_plugins_dir))

    # Add the directories to sys.path if they're not already included
    for dir_path in search_paths:
        if dir_path not in sys.path:
            sys.path.insert(0, dir_path)

    module_name = package_name.split('.')[-1].replace('-', '_')
    return importlib.import_module(module_name)


def installed_plugins(only_conda=False):
    """
    .. versionadded:: 0.20

    Parameters
    ----------
    only_conda : bool, optional
        Only consider plugins that are installed **as Conda packages**.

        .. versionadded:: 0.22

    Returns
    -------
    list
        List of properties corresponding to each available plugin that is
        **installed**.

        .. versionchanged:: 0.22

            If :data:`only_conda` is ``False``, a plugin is assumed to be
            *installed* if it is present in the
            ``share/microdrop/plugins/available`` directory **and** is a
            **real** directory (i.e., not a link).

            If :data:`only_conda` is ``True``, only properties for plugins that
            are installed **as Conda packages** are returned.
    """
    available_path = MICRODROP_CONDA_SHARE / 'plugins' / 'available'
    if not available_path.is_dir():
        return []

    installed_plugins_ = []
    for plugin_path in available_path.iterdir():
        # Skip if the entry is not a directory or it's a symbolic link
        if not plugin_path.is_dir() or plugin_path.is_symlink():
            continue

        # Read plugin package info from `properties.yml` file
        properties_file = plugin_path / 'properties.yml'
        try:
            with properties_file.open('r') as input_:
                properties_i = yaml.safe_load(input_)
                properties_i['path'] = str(plugin_path.resolve())
                installed_plugins_.append(properties_i)
        except Exception as e:
            logger.info('[warning] Could not read package info: `%s`, %s',
                        properties_file, e, exc_info=True)

    if only_conda:
        # Filter for plugins installed as Conda packages
        try:
            package_names = [plugin['package_name'] for plugin in installed_plugins_]
            conda_package_infos = ch.package_version(package_names, verbose=False)
            installed_package_names = set(pkg_info['name'] for pkg_info in conda_package_infos)
            return [plugin for plugin in installed_plugins_ if plugin['package_name'] in installed_package_names]
        except ch.PackageNotFound as exception:
            logger.warning(str(exception))
            return [plugin for plugin in installed_plugins_ if plugin['package_name'] in exception.available]
    else:
        return installed_plugins_


def enabled_plugins(installed_only=True):
    '''
    .. versionadded:: 0.21

    Parameters
    ----------
    installed_only : bool, optional
        Only consider enabled plugins that are installed in the Conda
        environment.

    Returns
    -------
    list
        List of properties corresponding to each plugin that is **enabled**.

        If :data:`installed_only` is True``, only consider plugins:

         1. Present in the ``etc/microdrop/plugins/enabled`` directory as a
            link/junction to a **real** directory (i.e., not a link) in the
            ``share/microdrop/plugins/available`` directory.
         2. Matching the name of a package in the Conda environment.

        If :data:`installed_only` is ``False``, consider all plugins present in
        the ``etc/microdrop/plugins/enabled`` directory as either a *real*
        directory or a link/junction.

    '''
    enabled_path = MICRODROP_CONDA_PLUGINS / 'enabled'
    if not enabled_path.is_dir():
        return []

    # Construct list of property dictionaries, one per enabled plugin
    # directory.
    enabled_plugins_ = []
    for plugin_path in enabled_path.iterdir():
        # Check condition based on 'installed_only' and if the path is a link
        if not installed_only or plugin_path.is_symlink():
            properties_file = plugin_path / 'properties.yml'
            try:
                with properties_file.open('r') as input_:
                    properties_i = yaml.safe_load(input_)
                    properties_i['path'] = str(plugin_path.resolve())
                    enabled_plugins_.append(properties_i)
            except Exception as e:
                logger.info('[warning] Could not read package info: `%s`, %s',
                            properties_file, e, exc_info=True)

    if installed_only:
        try:
            package_names = [plugin['package_name'] for plugin in enabled_plugins_]
            installed_info = ch.package_version(package_names, verbose=False)
            installed_package_names = {info['name'] for info in installed_info}

            return [plugin for plugin in enabled_plugins_ if plugin['package_name'] in installed_package_names]

        except ch.PackageNotFound as exception:
            logger.warning(str(exception))
            available_names = {package['name'] for package in exception.available}

            return [plugin for plugin in enabled_plugins_ if plugin['package_name'] in available_names]

    # Return list of all enabled plugins, regardless of whether or not they
    # have corresponding Conda packages installed.
    return enabled_plugins_
