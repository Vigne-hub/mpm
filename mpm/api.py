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
from microdrop_libs.path_helpers import path
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
    dir_path = path(dir_path)
    if platform.system() == 'Windows':
        if dir_path.isjunction():
            return True
    elif dir_path.islink():
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
    pathlib.path, dict
        path to which action was written and action object, including list of
        revisions for active Conda environment.
    """
    # Get list of revisions to Conda environment since creation.
    revisions_js = ch.conda_exec('list', '--revisions', '--json',
                                 verbose=False)
    revisions = json.loads(revisions_js)
    # Save list of revisions to `/etc/microdrop/plugins/actions/rev<rev>.json`
    # See [wheeler-microfluidics/microdrop#200][i200].
    #
    # [i200]: https://github.com/wheeler-microfluidics/microdrop/issues/200
    action = extra_context.copy() if extra_context else {}
    action['revisions'] = revisions
    action_path = (MICRODROP_CONDA_ACTIONS
                   .joinpath('rev{}.json.bz2'.format(revisions[-1]['rev'])))
    action_path.parent.makedirs_p()
    # Compress action file using bz2 to save disk space.
    with bz2.open(action_path, mode='wt', compresslevel=9) as output:
        json.dump(action, output, indent=2)

    return action_path, action


def _remove_broken_links():
    '''
    Remove broken links in `<conda prefix>/etc/microdrop/plugins/enabled/`.

    Returns
    -------
    list
        List of links removed (if any).
    '''
    enabled_dir = MICRODROP_CONDA_PLUGINS.joinpath('enabled')
    if not enabled_dir.isdir():
        return []

    broken_links = []
    for dir_i in enabled_dir.walkdirs(errors='ignore'):
        if platform.system() == 'Windows':
            if dir_i.isjunction() and not dir_i.readlink().isdir():
                # Junction/link target no longer exists.
                broken_links.append(dir_i)
        else:
            # currently do not support non windows
            raise NotImplementedError('Unsupported platform')

    removed_links = []
    for link_i in broken_links:
        try:
            link_i.unlink()
        except:
            pass
        else:
            removed_links.append(link_i)
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
    plugin_name = [plugin_name] if isinstance(plugin_name, str) else plugin_name

    # Perform installation
    conda_args = (['install', '-y', '--json'] + list(args) + plugin_name)
    install_log_js = ch.conda_exec(*conda_args, verbose=False)
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
    action_file = sorted([(int(cre_rev.match(file_i.namebase).group('rev')),
                           file_i) for file_i in
                          action_files if cre_rev.match(file_i.namebase)],
                         reverse=True)[0]
    # Do rollback (i.e., install state of previous revision).
    if action_file[1].ext.lower() == '.bz2':
        # Assume file is compressed using bz2.
        with bz2.BZ2File(action_file, mode='r') as input_:
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
    if isinstance(plugin_name, str):
        plugin_name = [plugin_name]

    available_path = MICRODROP_CONDA_SHARE.joinpath('plugins', 'available')
    for name_i in plugin_name:
        plugin_module_i = name_i.split('.')[-1].replace('-', '_')
        plugin_path_i = available_path.joinpath(plugin_module_i)
        if not _islinklike(plugin_path_i) and not plugin_path_i.isdir():
            raise IOError('Plugin `{}` not found in `{}`'
                          .format(name_i, available_path))
        else:
            logger.debug(f'[uninstall] Found plugin `{plugin_path_i}`')

    # Perform uninstall operation.
    conda_args = ['uninstall', '--json', '-y'] + list(args) + plugin_name
    uninstall_log_js = ch.conda_exec(*conda_args, verbose=False)
    # Remove broken links in `<conda prefix>/etc/microdrop/plugins/enabled/`,
    # since uninstall may have made one or more packages unavailable.
    _remove_broken_links()
    logger.debug(f'Uninstalled plugins: {plugin_name}')
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
        plugin_name = [plugin_name]
        singleton = True
    else:
        singleton = False

    # Conda-managed plugins
    shared_available_path = MICRODROP_CONDA_SHARE.joinpath('plugins',
                                                           'available')
    # User-managed plugins
    etc_available_path = MICRODROP_CONDA_ETC.joinpath('plugins', 'available')

    available_paths = (etc_available_path, shared_available_path)
    plugin_paths = []
    for name_i in plugin_name:
        for available_path_j in available_paths:
            plugin_path_ij = available_path_j.joinpath(name_i)
            if not _islinklike(plugin_path_ij) and plugin_path_ij.isdir():
                logger.debug('Found plugin directory: `%s`', plugin_path_ij)
                break
        else:
            raise IOError('Plugin `{}` not found in `{}` or `{}`'
                          .format(name_i, *available_paths))
        plugin_paths.append(plugin_path_ij)

    # All specified plugins are available.

    # Link all specified plugins in
    # `<conda prefix>/etc/microdrop/plugins/enabled/` (if not already linked).
    enabled_path = MICRODROP_CONDA_PLUGINS.joinpath('enabled')
    enabled_path.makedirs_p()

    # Set flag for each plugin: `False` iff the plugin was already enabled,
    # `True` iff it was just enabled now.
    enabled_now = {}
    for plugin_path_i in plugin_paths:
        plugin_link_path_i = enabled_path.joinpath(plugin_path_i.name)
        if not plugin_link_path_i.exists():
            if platform.system() == 'Windows':
                plugin_path_i.junction(plugin_link_path_i)
            else:
                plugin_path_i.symlink(plugin_link_path_i)
            logger.debug('Enabled plugin directory: `%s` -> `%s`',
                         plugin_path_i, plugin_link_path_i)
            enabled_now[plugin_path_i.name] = True
        else:
            logger.debug('Plugin already enabled: `%s` -> `%s`', plugin_path_i,
                         plugin_link_path_i)
            enabled_now[plugin_path_i.name] = False
    return enabled_now if not singleton else enabled_now.values()[0]


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
    if isinstance(plugin_name, str):
        plugin_name = [plugin_name]

    # Verify all specified plugins are currently enabled.
    enabled_path = MICRODROP_CONDA_PLUGINS.joinpath('enabled')
    for name_i in plugin_name:
        plugin_path_i = enabled_path.joinpath(name_i)
        if not _islinklike(plugin_path_i) and not plugin_path_i.isdir():
            raise IOError('Plugin `{}` not found in `{}`'
                          .format(name_i, enabled_path))

    # All specified plugins are enabled.

    # Remove all specified plugins from
    # `<conda prefix>/etc/microdrop/plugins/enabled/`.
    for name_i in plugin_name:
        plugin_link_path_i = enabled_path.joinpath(name_i)
        plugin_link_path_i.unlink()
        logger.debug('Disabled plugin `%s` (i.e., removed `%s`)',
                     plugin_path_i, plugin_link_path_i)


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

    # Only consider **installed** plugins (see `installed_plugins()` docstring).
    installed_plugins_ = installed_plugins(only_conda=True)

    if installed_plugins_:
        plugin_packages = [plugin_i['package_name']
                           for plugin_i in installed_plugins_]
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
    available_plugins_dir = MICRODROP_CONDA_SHARE.joinpath('plugins',
                                                           'available')
    enabled_plugins_dir = MICRODROP_CONDA_ETC.joinpath('plugins', 'enabled')
    search_paths = [enabled_plugins_dir]
    if include_available:
        search_paths += [available_plugins_dir]
    for dir_i in search_paths:
        if dir_i not in sys.path:
            sys.path.insert(0, dir_i)
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
    available_path = MICRODROP_CONDA_SHARE.joinpath('plugins', 'available')
    if not available_path.isdir():
        return []

    installed_plugins_ = []
    for plugin_path_i in available_path.dirs():
        # Only process plugin directory if it is *not a link*.
        if not _islinklike(plugin_path_i):
            # Read plugin package info from `properties.yml` file.
            try:
                with plugin_path_i.joinpath('properties.yml').open('r') as input_:
                    properties_i = yaml.load(input_.read())
            except:
                logger.info('[warning] Could not read package info: `%s`',
                            plugin_path_i.joinpath('properties.yml'),
                            exc_info=True)
            else:
                properties_i['path'] = plugin_path_i.realpath()
                installed_plugins_.append(properties_i)

    if only_conda:
        # Filter for plugins installed as Conda packages
        try:
            package_names = [plugin_i['package_name']
                             for plugin_i in installed_plugins_]
            conda_package_infos = ch.package_version(package_names,
                                                     verbose=False)
        except ch.PackageNotFound as exception:
            # At least one specified plugin package name did not correspond to an
            # installed Conda package.
            logger.warning(str(exception))
            conda_package_infos = exception.available
        # Extract name from each Conda plugin package.
        installed_package_names = set([package_i['name']
                                       for package_i in conda_package_infos])
        return [plugin_i for plugin_i in installed_plugins_
                if plugin_i['package_name'] in installed_package_names]
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
    enabled_path = MICRODROP_CONDA_PLUGINS.joinpath('enabled')
    if not enabled_path.isdir():
        return []

    # Construct list of property dictionaries, one per enabled plugin
    # directory.
    enabled_plugins_ = []
    for plugin_path_i in enabled_path.dirs():
        if not installed_only or _islinklike(plugin_path_i):
            # Enabled plugin path is either **a link to an installed plugin**
            # or call explicitly specifies that plugins that are not installed
            # should still be considered.

            # Read plugin package info from `properties.yml` file.
            try:
                with plugin_path_i.joinpath('properties.yml').open('r') as input_:
                    properties_i = yaml.safe_load(input_.read())
            except:
                logger.info('[warning] Could not read package info: `%s`',
                            plugin_path_i.joinpath('properties.yml'),
                            exc_info=True)
                continue
            else:
                properties_i['path'] = plugin_path_i.realpath()
                enabled_plugins_.append(properties_i)

    if installed_only:
        try:
            # Attempt to look up installed Conda package info for each enabled
            # plugin.
            package_names = [properties_i['package_name']
                             for properties_i in enabled_plugins_]
            installed_info = ch.package_version(package_names, verbose=False)
        except ch.PackageNotFound as exception:
            # Failed to find a corresponding installed Conda package for at
            # least one enabled plugin.
            logger.warning(str(exception))
            available_names = set([package_i['name']
                                   for package_i in exception.available])
            # Only return list of enabled plugins that have a corresponding
            # Conda package installed.
            return [properties_i for properties_i in enabled_plugins_
                    if properties_i['package_name'] in available_names]

    # Return list of all enabled plugins, regardless of whether or not they
    # have corresponding Conda packages installed.
    return enabled_plugins_
