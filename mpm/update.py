import conda_helpers as ch

from .api import install as plugin_install


def _update_plugin(package_name):
    '''
    Update plugin (no user interface).

    .. versionadded:: 0.19

    Parameters
    ----------
    package_name : str, optional
        Conda MicroDrop plugin package name, e.g., `microdrop.mr-box-plugin`.

    Returns
    -------
    dict
        If plugin was updated successfully, output will *at least* contain
        items with the keys ``old_versions`` and ``new_versions``.

        If no update was available, output will *at least* contain an item with
        the key ``version`` and will **not** contain the keys ``old_versions``
        and ``new_versions``.

    Raises
    ------
    IOError
        If Conda update server cannot be reached, e.g., if there is no network
        connection available.

    See also
    --------
    _update_plugin_ui
    '''
    try:
        update_json_log = plugin_install(package_name)
    except RuntimeError as exception:
        if 'CondaHTTPError' in str(exception):
            raise IOError('Error accessing update server.')
        else:
            raise

    if update_json_log.get('success'):
        if 'actions' in update_json_log:
            # Plugin was updated successfully.
            # Display prompt indicating previous version
            # and new version.
            actions = update_json_log['actions']
            update_json_log['old_versions'] = actions.get('UNLINK', [])
            update_json_log['new_versions'] = actions.get('LINK', [])
        else:
            # No update available.
            version_dict = ch.package_version(package_name)
            update_json_log.update(version_dict)
        return update_json_log
