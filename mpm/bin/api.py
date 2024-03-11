# coding: utf-8
from argparse import ArgumentParser
import json
import logging
import sys

from . import LOG_PARSER
from ..api import (MICRODROP_CONDA_ETC, MICRODROP_CONDA_SHARE, disable_plugin,
                   enable_plugin)


PLUGIN_PARSER = ArgumentParser(add_help=False, parents=[LOG_PARSER])
PLUGIN_PARSER.add_argument('--json', action='store_true',
                           help='Set output format to JSON.')
subparsers = PLUGIN_PARSER.add_subparsers(help='help for subcommand',
                                       dest='command')

enable_parser = subparsers.add_parser('enable', help='Enable one or more '
                                      'available plugins.')
enable_parser.add_argument('plugin', nargs='+', default=[])

disable_parser = subparsers.add_parser('disable', help='Disable one or more '
                                       'available plugins.')
disable_parser.add_argument('plugin', nargs='+', default=[])

enabled_parser = subparsers.add_parser('enabled', help='List enabled plugins.')
list_parser = subparsers.add_parser('list', help='List available plugins.')


def parse_args(args=None):
    '''Parses arguments, returns ``(options, args)``.'''
    if args is None:
        args = sys.argv[1:]

    parser = ArgumentParser(description='Actions related to available '
                            'MicroDrop Conda package plugin(s).',
                            parents=[PLUGIN_PARSER])

    return parser.parse_args()



def _dump_list(list_data, jsonify, stream=sys.stdout):
    '''
    Dump list to output stream, optionally encoded as JSON.

    Parameters
    ----------
    list_data : list
    jsonify : bool
    stream : file-like
    '''
    if not jsonify and list_data:
        print('\n'.join(list_data), file=stream)
    else:
        print(json.dumps(list_data), file=stream)


def main(args=None):
    if args is None:
        args = parse_args()

    # Log to `stderr` to leave `stdout` output intact.
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        stream=sys.stderr)

    if args.command == 'list':
        available_plugin_paths = sorted(MICRODROP_CONDA_SHARE
                                        .joinpath('plugins',
                                                  'available').dirs())
        available_plugins = map(str, [plugin_i.name
                                      for plugin_i in available_plugin_paths])
        _dump_list(available_plugins, args.json)
    elif args.command == 'enabled':
        enabled_plugin_paths = sorted(MICRODROP_CONDA_ETC
                                      .joinpath('plugins', 'enabled').dirs())
        enabled_plugins = map(str, [plugin_i.name
                                    for plugin_i in enabled_plugin_paths])
        _dump_list(enabled_plugins, args.json)
    elif args.command == 'enable':
        enabled_now = enable_plugin(args.plugin)
        enabled_plugins = sorted([name_i for name_i, enabled_i in
                                  enabled_now.items() if enabled_i])

        # Print list of plugins that were enabled (do not print names of
        # plugins that were already enabled).
        _dump_list(enabled_plugins, args.json)
    elif args.command == 'disable':
        try:
            disable_plugin(args.plugin)
            disabled_plugins = sorted(args.plugin)
        except IOError as exception:
            if 'not found in' in str(exception):
                logging.error(str(exception))
                # No plugins were disabled since at least one plugin was not
                # found.
                _dump_list([], args.json)
        else:
            _dump_list(disabled_plugins, args.json)