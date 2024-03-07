# coding: utf-8
from argparse import ArgumentParser
from collections import OrderedDict
import datetime as dt
import logging
import sys
from path_helpers import path
import si_prefix as si

from .. import pformat_dict
from ..commands import (DEFAULT_INDEX_HOST, freeze, get_plugins_directory,
                        install, SERVER_URL_TEMPLATE, uninstall, search)
from ..hooks import on_plugin_install

logger = logging.getLogger(__name__)

default_plugins_directory = get_plugins_directory()
default_config_path = (default_plugins_directory.parent
                       .joinpath('microdrop.ini'))

# Parsers that may be reused by other modules.
LOG_PARSER = ArgumentParser(add_help=False)
LOG_PARSER.add_argument('-l', '--log-level', default='error',
                        choices=['error', 'debug', 'info'])
CONFIG_PARSER_ARGS = (('-c', '--config-file'),
                      dict(type=path, help='MicroDrop config file '
                                           '(default="{default}").'
                           .format(default=default_config_path)))
CONFIG_PARSER = ArgumentParser(add_help=False)
CONFIG_PARSER.add_argument(*CONFIG_PARSER_ARGS[0], **CONFIG_PARSER_ARGS[1])

SERVER_PARSER = ArgumentParser(add_help=False)
SERVER_PARSER.add_argument('-s', '--server-url',
                           default=DEFAULT_INDEX_HOST, help='MicroDrop '
                                                            'plugin index URL (default="%(default)s")')
PLUGINS_PARSER = ArgumentParser(add_help=False)
PLUGINS_PARSER.add_argument('plugin', nargs='+')

PLUGINS_DIR_PARSER = ArgumentParser(add_help=False)
mutex_path = PLUGINS_DIR_PARSER.add_mutually_exclusive_group()
mutex_path.add_argument(*CONFIG_PARSER_ARGS[0], **CONFIG_PARSER_ARGS[1])
mutex_path.add_argument('-d', '--plugins-directory', type=path,
                        help='MicroDrop plugins directory '
                             '(default="{default}").'
                        .format(default=default_plugins_directory))

MPM_PARSER = ArgumentParser(add_help=False, parents=[LOG_PARSER,
                                                     PLUGINS_DIR_PARSER])

subparsers = MPM_PARSER.add_subparsers(help='help for subcommand',
                                       dest='command')
install_parser = subparsers.add_parser('install', help='Install plugins.',
                                       parents=[SERVER_PARSER])
install_parser.add_argument('--no-on-install', action='store_true',
                            help='Do not run `on_plugin_install` hook after '
                                 'installing plugin')
plugin_group = install_parser.add_mutually_exclusive_group(required=True)
plugin_group.add_argument('-r', '--requirements-file', type=path)
plugin_group.add_argument('plugin', nargs='*', default=[])

search_parser = subparsers.add_parser('search', help='Search server for '
                                                     'plugin.', parents=[SERVER_PARSER])
search_parser.add_argument('plugin')

subparsers.add_parser('uninstall', help='Uninstall plugins.',
                      parents=[PLUGINS_PARSER])

subparsers.add_parser('freeze', help='Output installed packages in '
                                     'requirements format.')

hook_parser = subparsers.add_parser('hook', help='Execute plugin hook')
hook_parser.add_argument('hook', choices=['on_install'], help='Plugin hook')
hook_parser.add_argument('plugin', nargs='*')


def parse_args(args=None):
    '''Parses arguments, returns ``(options, args)``.'''
    if args is None:
        args = sys.argv

    parser = ArgumentParser(description='MicroDrop plugin manager',
                            parents=[MPM_PARSER])

    return parser.parse_args(args=args)


def validate_args(args):
    '''
    Apply custom validation and actions based on parsed arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Result from ``parse_args`` method of ``argparse.ArgumentParser``
        instance.

    Returns
    -------
    argparse.Namespace
        Reference to input ``args``, which have been validated/updated.
    '''
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    if getattr(args, 'command', None) == 'install':
        if args.requirements_file and not args.requirements_file.is_file():
            print('Requirements file not available: {}'
                  .format(args.requirements_file), file=sys.stderr)
            raise SystemExit(-1)
        elif not args.plugin and not args.requirements_file:
            print('Requirements file or at least one plugin must be specified.', file=sys.stderr)
            raise SystemExit(-2)
    if hasattr(args, 'server_url'):
        logger.debug('Using MicroDrop index server: "%s"', args.server_url)
        args.server_url = SERVER_URL_TEMPLATE % args.server_url
    if all([args.plugins_directory is None,
            args.config_file is None]):
        args.plugins_directory = get_plugins_directory()
    elif args.plugins_directory is None:
        args.config_file = args.config_file.resolve()
        args.plugins_directory = get_plugins_directory(config_path=args.config_file)
    else:
        args.plugins_directory = args.plugins_directory.resolve()
    return args


def main(args=None):
    if args is None:
        args = parse_args()
    args = validate_args(args)
    logger.debug('Arguments: %s', pformat_dict(vars(args)))
    if args.command == 'freeze':
        print('\n'.join(freeze(plugins_directory=args.plugins_directory)))
    elif args.command == 'hook':
        if not args.plugin:
            plugin_paths = list(args.plugins_directory.glob('*'))
        else:
            plugin_paths = [args.plugins_directory / p for p in args.plugin]
        print(50 * '*')
        print('# Processing `on_install` hook for: #\n')
        print('\n'.join(['  - {}{}'.format(p.name, '' if p.exists()
        else ' (not found)')
                         for p in plugin_paths]))
        print('')
        if args.hook == 'on_install':
            for plugin_path_i in plugin_paths:
                print(50 * '-')
                if plugin_path_i.exists():
                    on_plugin_install(plugin_path_i)
                else:
                    print('[warning] Skipping missing plugin', file=sys.stderr)
    elif args.command == 'install':
        if args.requirements_file:
            with args.requirements_file.open() as file:
                args.plugin = [line.strip() for line in file
                               if not line.startswith('#')]
        for plugin_i in args.plugin:
            try:
                path_i, meta_i = install(plugin_package=plugin_i,
                                         plugins_directory=args.plugins_directory,
                                         server_url=args.server_url)
                if not args.no_on_install:
                    on_plugin_install(path_i)
            except KeyError as exception:
                print(f'[{plugin_i}] {exception.args[0]}')
            except ValueError as exception:
                print(exception.args[0])
                continue
    elif args.command == 'search':
        try:
            plugin_name, releases = search(plugin_package=args.plugin[0],
                                           server_url=args.server_url)
            release_info = OrderedDict()
            release_info['plugin_name'] = [plugin_name] + ((len(releases) - 1) * [''])
            release_info['version'] = list(releases.keys())

            for k in ['upload_time', 'size']:
                release_info[k] = [r[k] for r in releases.values()]

            release_info['upload_time'] = [dt.datetime.strptime(timestamp,
                                                                '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d %H:%M') for
                                           timestamp in release_info['upload_time']]
            release_info['size'] = [si.si_format(s, precision=0, format_str='{value} {prefix}B') for s in
                                    release_info['size']]

            print('\n' + pformat_dict(release_info))
        except KeyError as exception:
            print(exception.args[0], file=sys.stderr)
    elif args.command == 'uninstall':
        for plugin_i in args.plugin:
            uninstall(plugin_package=plugin_i, plugins_directory=args.plugins_directory)


if __name__ == '__main__':
    main()
