# coding: utf-8
'''
Inspired by `pip`.

::

    mpm install <plugin-name>[(==|>|>=|<=)version] [<plugin-name>[(==|>|>=|<=)version]...]
    mpm install -r plugin_requirements.txt
    mpm uninstall <plugin-name>
    mpm freeze
'''
import io
import logging
import os
import tempfile as tmp

from pathlib import Path
from microdrop import configobj_micro as configobj
import progressbar
import requests
import tarfile
import yaml

# TODO: Replace usage of pip helpers if possible
from pip_helpers import CRE_PACKAGE, get_releases

logger = logging.getLogger(__name__)

DEFAULT_INDEX_HOST = r'http://microfluidics.utoronto.ca/update'
SERVER_URL_TEMPLATE = r'%s/plugins/{}/json/'
DEFAULT_SERVER_URL = SERVER_URL_TEMPLATE % DEFAULT_INDEX_HOST


def home_dir():
    """
    Returns:

        str : Path to home directory (or ``Documents`` directory on Windows).
    """
    if os.name == 'nt':
        from win32comext.shell import shell, shellcon

        return shell.SHGetFolderPath(0, shellcon.CSIDL_PERSONAL, 0, 0)
    else:
        return os.path.expanduser('~')


def get_plugins_directory(config_path=None, microdrop_user_root=None):
    '''
    Resolve plugins directory.

    Plugins directory is resolved as follows, highest-priority first:

     1. ``plugins`` directory specified in provided :data:`config_path`.
     2. ``plugins`` sub-directory of specified MicroDrop profile path (i.e.,
        :data:`microdrop_user_root`)
     3. ``plugins`` sub-directory of parent directory of configuration file
        path specified using ``MICRODROP_CONFIG`` environment variable.
     4. ``plugins`` sub-directory of MicroDrop profile path specified using
        ``MICRODROP_PROFILE`` environment variable.
     5. Plugins directory specified in
        ``<home directory>/MicroDrop/microdrop.ini``.
     6. Plugins directory in default profile location, i.e.,
        ``<home directory>/MicroDrop/plugins``.

    Parameters
    ----------
    config_path : str, optional
        Configuration file path (i.e., path to ``microdrop.ini``).
    microdrop_user_root : str, optional
        Path to MicroDrop user data directory.

    Returns
    -------
    path
        Absolute path to plugins directory.
    '''
    RESOLVED_BY_NONE = 'default'
    RESOLVED_BY_CONFIG_ARG = 'config_path argument'
    RESOLVED_BY_PROFILE_ARG = 'microdrop_user_root argument'
    RESOLVED_BY_CONFIG_ENV = 'MICRODROP_CONFIG environment variable'
    RESOLVED_BY_PROFILE_ENV = 'MICRODROP_PROFILE environment variable'

    resolved_by = [RESOLVED_BY_NONE]

    # # Find plugins directory path #
    if microdrop_user_root is not None:
        microdrop_user_root = Path(microdrop_user_root).resolve()
        resolved_by.append(RESOLVED_BY_PROFILE_ARG)
    elif 'MICRODROP_PROFILE' in os.environ:
        microdrop_user_root = Path(os.environ['MICRODROP_PROFILE']).resolve()
        resolved_by.append(RESOLVED_BY_PROFILE_ENV)
    else:
        microdrop_user_root = Path(home_dir()).joinpath('MicroDrop')

    if config_path is not None:
        config_path = Path(config_path).resolve()
        resolved_by.append(RESOLVED_BY_CONFIG_ARG)
    elif 'MICRODROP_CONFIG' in os.environ:
        config_path = Path(os.environ['MICRODROP_CONFIG']).resolve()
        resolved_by.append(RESOLVED_BY_CONFIG_ENV)
    else:
        config_path = microdrop_user_root.joinpath('microdrop.ini')

    try:
        # Look up plugins directory stored in configuration file.
        plugins_directory = Path(configobj.ConfigObj(str(config_path))['plugins']['directory']).resolve()
        if not plugins_directory.is_absolute():
            # Plugins directory stored in configuration file as relative path.
            # Interpret as relative to parent directory of configuration file.
            plugins_directory = config_path.parent.joinpath(plugins_directory)
        if not plugins_directory.is_dir():
            raise IOError('Plugins directory does not exist: {}'
                          .format(plugins_directory))
    except Exception as why:
        # Error looking up plugins directory in configuration file (maybe no
        # plugins directory was listed in configuration file?).
        plugins_directory = microdrop_user_root.joinpath('plugins')
        logger.warning('%s.  Using default plugins directory: %s', why,
                       plugins_directory)
        if resolved_by[-1] in (RESOLVED_BY_CONFIG_ARG, RESOLVED_BY_CONFIG_ENV):
            resolved_by.pop()
    logger.info('Resolved plugins directory by %s: %s', resolved_by[-1],
                plugins_directory)
    return plugins_directory


def plugin_request(plugin_str):
    """
    Extract plugin name and version specifiers from plugin descriptor string.

    .. versionchanged:: 0.25.2
        Import from `pip_helpers` locally to avoid error `sci-bots/mpm#5`_.

        .. _sci-bots/mpm#5: https://github.com/sci-bots/mpm/issues/5
    """

    match = CRE_PACKAGE.match(plugin_str)
    if not match:
        raise ValueError('Invalid plugin descriptor. Must be like "foo", '
                         '"foo==1.0", "foo>=1.0", etc.')
    return match.groupdict()


def install(plugin_package, plugins_directory, server_url=DEFAULT_SERVER_URL):
    """
    Parameters
    ----------
    plugin_package : str
        Name of plugin package hosted on MicroDrop plugin index. Version
        constraints are also supported (e.g., ``"foo", "foo==1.0",
        "foo>=1.0"``, etc.)  See `version specifiers`_ reference for more
        details.
    plugins_directory : str
        Path to MicroDrop user plugins directory.
    server_url : str
        URL of JSON request for MicroDrop plugins package index.  See
        ``DEFAULT_SERVER_URL`` for default.

    Returns
    -------
    (path, dict)
        Path to directory of installed plugin and plugin package metadata
        dictionary.


    .. _version specifiers:
        https://www.python.org/dev/peps/pep-0440/#version-specifiers

    .. versionchanged:: 0.25.2
        Import `pip_helpers` locally to avoid error `sci-bots/mpm#5`_.

        .. _sci-bots/mpm#5: https://github.com/sci-bots/mpm/issues/5
    """
    plugins_directory = Path(plugins_directory)
    if Path(plugin_package).is_file():
        plugin_is_file = True
        with open(plugin_package, 'rb') as plugin_file:
            # Plugin package is a file.
            plugin_file_metadata = extract_metadata(plugin_file)
        name = plugin_file_metadata['package_name']
        version = plugin_file_metadata['version']
    else:
        plugin_is_file = False
        # Look up latest release matching specifiers.
        try:
            name, releases = get_releases(plugin_package,
                                          server_url=server_url)
            version, release = list(releases.items())[-1]
        except KeyError:
            raise

    # Check existing version (if any).
    try:
        plugin_path = plugins_directory.joinpath(name)
    except:
        plugin_path = Path(plugins_directory).joinpath(name)

    if not plugin_path.is_dir():
        existing_version = None
    else:
        plugin_metadata = yaml.safe_load(plugin_path.joinpath('properties.yml')
                                         .read_text())
        existing_version = plugin_metadata['version']

    if version == existing_version:
        # Package already installed.
        raise ValueError('`{}=={}` is already installed.'.format(name,
                                                                 version))

    if existing_version is not None:
        # Uninstall existing package.
        uninstall(name, str(plugins_directory))

    # Assuming 'name' and 'version' variables are defined
    print(f'Installing `{name}=={version}`.')

    if not plugin_is_file:
        # Download plugin release archive.
        download = requests.get(release['url'], stream=True)

        # Use io.BytesIO for a bytes buffer
        plugin_archive_bytes = io.BytesIO()
        total_bytes = int(download.headers.get('Content-Length'))
        bytes_read = 0

        # Set up the progress bar
        with progressbar.ProgressBar(max_value=total_bytes) as bar:
            for chunk in download.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive chunks
                    bytes_read += len(chunk)
                    plugin_archive_bytes.write(chunk)
                    bar.update(bytes_read)

        # Reset the stream position to the beginning before reading from it
        plugin_archive_bytes.seek(0)
    else:
        # Open the plugin package as a binary file
        plugin_archive_bytes = open(plugin_package, 'rb')

    # Assuming 'install_fileobj', 'plugin_path', and 'plugin_metadata' functions or variables are defined
    plugin_path, plugin_metadata = install_fileobj(plugin_archive_bytes, plugin_path)

    # Ensure installed package and version match the requested version
    assert plugin_metadata['package_name'] == name and plugin_metadata['version'] == version, "Version mismatch error."

    print("  \--> done")

    # Close the file object
    plugin_archive_bytes.close()

    # Assuming 'plugin_path' and 'plugin_metadata' are used further
    return plugin_path, plugin_metadata


def extract_metadata(fileobj):
    '''
    Extract metadata from plugin archive file-like object (e.g., opened file,
    ``StringIO``).

    Parameters
    ----------
    fileobj : file-like
        MicroDrop plugin archive file object.

    Returns
    -------
    dict
        Metadata dictionary for plugin.
    '''
    tar = tarfile.open(mode="r:gz", fileobj=fileobj)

    plugin_path = Path(tmp.mkdtemp(prefix='mpm-'))
    try:
        tar.extractall(path=str(plugin_path))

        properties_path = plugin_path.joinpath('properties.yml')
        return yaml.safe_load(properties_path.read_text())

    finally:
        fileobj.seek(0)
        for item in plugin_path.glob('*'):
            if item.is_dir():
                item.rmdir()
            else:
                item.unlink()
        plugin_path.rmdir()


def install_fileobj(fileobj, plugin_path):
    """
    Extract and install plugin from file-like object (e.g., opened file,
    ``StringIO``).

    Parameters
    ----------
    fileobj : file-like
        MicroDrop plugin file object to extract and install.
    plugin_path : path
        Target plugin install directory path.

    Returns
    -------
    (path, dict)
        Directory of installed plugin and metadata dictionary for plugin.
    """
    plugin_path = Path(plugin_path)
    tar = tarfile.open(mode="r:gz", fileobj=fileobj)

    try:
        tar.extractall(path=str(plugin_path))

        plugin_metadata = yaml.safe_load(plugin_path.joinpath('properties.yml').read_text())
        fileobj.seek(0)
    except:
        # Error occured, so delete extracted plugin.
        plugin_path.rmdir()
        raise

    # TODO Handle `requirements.txt`.
    return plugin_path, plugin_metadata


def uninstall(plugin_package, plugins_directory):
    """
    Parameters
    ----------
    plugin_package : str
        Name of plugin package hosted on MicroDrop plugin index.
    plugins_directory : str
        Path to MicroDrop user plugins directory.
    """
    plugin_path = Path(plugins_directory).joinpath(plugin_package)

    if not plugin_path.is_dir():
        raise IOError('Plugin `%s` is not installed in `%s`' %
                      (plugin_package, plugins_directory))
    else:
        try:
            plugin_metadata = yaml.safe_load(plugin_path.joinpath('properties.yml').read_text())
            existing_version = plugin_metadata.get('version')
        except:
            existing_version = None

    if existing_version is not None:
        # Uninstall existing package.
        print('Uninstalling `{}=={}`.'.format(plugin_package, existing_version))
    else:
        print('Uninstalling `{}`.'.format(plugin_package))

    # Uninstall latest release
    # ======================
    for item in plugin_path.glob('*'):
        if item.is_dir():
            item.rmdir()
        else:
            item.unlink()
    plugin_path.rmdir()
    print('  \--> done')


def freeze(plugins_directory):
    '''
    Parameters
    ----------
    plugins_directory : str
        Path to MicroDrop user plugins directory.

    Returns
    -------
    list
        List of package strings corresponding to installed plugin versions.
    '''
    # Check existing version (if any).
    package_versions = []
    for plugin_path_i in Path(plugins_directory).iterdir():
        if plugin_path_i.is_dir():
            try:
                plugin_metadata = yaml.safe_load(plugin_path_i.joinpath('properties.yml').read_text())
                if plugin_path_i.name != plugin_metadata['package_name']:
                    continue
                package_versions.append((plugin_metadata['package_name'], plugin_metadata['version']))
            except:
                continue
    return ['%s==%s' % v for v in package_versions]


def search(plugin_package, server_url=DEFAULT_SERVER_URL):
    '''
    Parameters
    ----------
    plugin_package : str
        Name of plugin package hosted on MicroDrop plugin index. Version
        constraints are also supported (e.g., ``"foo", "foo==1.0",
        "foo>=1.0"``, etc.)  See `version specifiers`_ reference for more
        details.
    server_url : str
        URL of JSON request for MicroDrop plugins package index.  See
        ``DEFAULT_SERVER_URL`` for default.

    Returns
    -------
    (str, OrderedDict)
        Name of found plugin and mapping of version strings to plugin package
        metadata dictionaries.


    .. _version specifiers:
        https://www.python.org/dev/peps/pep-0440/#version-specifiers

    .. versionchanged:: 0.25.2
        Import `pip_helpers` locally to avoid error `sci-bots/mpm#5`_.

        .. _sci-bots/mpm#5: https://github.com/sci-bots/mpm/issues/5
    '''

    # Look up latest release matching specifiers.
    return get_releases(plugin_package, server_url=server_url)
