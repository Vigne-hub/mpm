import logging
import threading
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, GObject

import conda_helpers as ch
import logging_helpers as lh

from ...api import installed_plugins, update

logger = logging.getLogger(__name__)


# In GTK3, GDK threads should be initialized like this, if needed. However,
# this is often not necessary in modern GTK3 applications unless you're directly
# using GDK in threads. GTK3 itself is thread-aware.
GObject.threads_init()  # Deprecated and usually not needed in GTK3

def update_plugin_dialog(package_name=None, update_args=None,
                         update_kwargs=None, ignore_not_installed=True):
    '''
    Launch dialog to track status of update of specified plugin package.

    Adjusted for Python 3.8 and GTK3.
    '''

    thread_context = {}

    if package_name is None:
        installed_plugins_ = installed_plugins(only_conda=True)
        installed_package_names = [plugin_i['package_name'] for plugin_i in installed_plugins_]
        package_name = installed_package_names
        logger.info('Update all plugins installed as Conda packages.')
    else:
        if isinstance(package_name, str):
            package_name = [package_name]

        try:
            conda_package_infos = ch.package_version(package_name, verbose=False)
        except ch.PackageNotFound as exception:
            if not ignore_not_installed:
                raise
            logger.warning(str(exception))
            conda_package_infos = exception.available

        package_name = [package_i['name'] for package_i in conda_package_infos]
        logger.info('Update the following plugins: %s', ', '.join('`{}`'.format(name_i) for name_i in package_name))

    package_name_list = ', '.join('`{}`'.format(name_i) for name_i in package_name)
    package_name_lines = '\n'.join(' - {}'.format(name_i) for name_i in package_name)

    def _update(update_complete, package_name):
        try:
            with lh.logging_restore(clear_handlers=True):
                args = update_args or []
                kwargs = update_kwargs or {}
                kwargs['package_name'] = package_name
                update_response = update(*args, **kwargs)
                thread_context['update_response'] = update_response

            install_info_ = ch.install_info(update_response)

            if any(install_info_):
                def _status():
                    updated_packages = []
                    for package_name_i in package_name:
                        if any(linked_i[0].startswith(package_name_i) for linked_i in install_info_[1]):
                            updated_packages.append(package_name_i)

                    if updated_packages:
                        message = ('The following plugin(s) were updated successfully:\n<b>{}</b>'
                                   .format(package_name_lines))
                    else:
                        message = 'Plugin dependencies were updated successfully.'
                    dialog.props.text = message
                GLib.idle_add(_status)
            else:
                def _status():
                    dialog.props.text = ('The latest version of the following plugin(s) are already installed:\n{}'
                                         .format(package_name_lines))
                GLib.idle_add(_status)
        except Exception as exception:
            def _error():
                dialog.props.text = ('Error updating the following plugin(s):\n{}'
                                     .format(package_name_lines))
            GLib.idle_add(_error)
            thread_context['update_response'] = None
        update_complete.set()

    def _pulse(update_complete, progress_bar):
        while not update_complete.wait(1. / 16):
            GLib.idle_add(progress_bar.pulse)

        def _on_complete():
            progress_bar.set_fraction(1.0)
            progress_bar.hide()

        GLib.idle_add(_on_complete)

    dialog = Gtk.MessageDialog(buttons=Gtk.ButtonsType.OK_CANCEL)
    dialog.set_position(Gtk.WindowPosition.MOUSE)
    dialog.props.resizable = True
    progress_bar = Gtk.ProgressBar()
    content_area = dialog.get_content_area()
    content_area.pack_start(progress_bar, True, True, 5)
    content_area.show_all()
    dialog.action_area.get_children()[1].set_sensitive(False)

    dialog.props.title = 'Update plugin'
    dialog.props.text = 'Searching for updates...'

    update_complete = threading.Event()

    progress_thread = threading.Thread(target=_pulse, args=(update_complete, progress_bar,))
    progress_thread.daemon = True
    progress_thread.start()

    update_thread = threading.Thread(target=_update, args=(update_complete, package_name,))
    update_thread.daemon = True
    update_thread.start()

    dialog.run()
    dialog.destroy()

    return thread_context.get('update_response')
