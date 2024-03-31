import argparse
import logging
import sys
from microdrop_libs.path_helpers import path

# Adjust these imports according to your project structure.
from ..hooks import on_plugin_install
from . import get_plugins_directory, LOG_PARSER, PLUGINS_DIR_PARSER

logger = logging.getLogger(__name__)

default_plugins_directory = get_plugins_directory()

INSTALL_REQUIREMENTS_PARSER = argparse.ArgumentParser(add_help=False, parents=[LOG_PARSER, PLUGINS_DIR_PARSER])


def validate_args(args):
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.DEBUG))

    if all([args.plugins_directory is None,
            args.config_file is None]):
        args.plugins_directory = default_plugins_directory
        logger.debug('Using default plugins directory: "%s"', args.plugins_directory)
    elif not args.plugins_directory:
        args.plugins_directory = get_plugins_directory(config_path=args.config_file)
        logger.debug('Plugins directory from config file: "%s"', args.plugins_directory)
    else:
        logger.debug('Using explicit plugins directory: "%s"', args.plugins_directory)
    return args


def install_dependencies(plugins_directory, ostream=sys.stdout):
    '''
    Run "on_plugin_install" script for each plugin directory found in
    the specified plugins directory.

    Parameters
    ----------
    plugins_directory : path or str
        File system path to directory containing zero or more plugin subdirectories.
    ostream : file-like
        Output stream for status messages (default: sys.stdout).
    '''
    plugin_directories = plugins_directory.realpath().dirs()

    print('*' * 50, file=ostream)
    print('Processing plugins:', file=ostream)
    print('\n'.join(['  - {}'.format(p) for p in plugin_directories]), file=ostream)
    print('\n' + '-' * 50 + '\n', file=ostream)

    for plugin_dir_i in plugin_directories:
        try:
            on_plugin_install(str(plugin_dir_i), ostream=ostream)
        except RuntimeError as exception:
            print(exception, file=ostream)
        print('\n' + '-' * 50 + '\n', file=ostream)


def parse_args(args=None):
    '''Parses arguments, returns the parsed arguments.'''
    if args is None:
        args = sys.argv[1:]  # Exclude the script name from the arguments.

    parser = argparse.ArgumentParser(description='MicroDrop plugin dependencies installer', parents=[INSTALL_REQUIREMENTS_PARSER])
    return parser.parse_args(args)


def main(cli_args=None):
    args = parse_args(cli_args)
    args = validate_args(args)
    logger.debug('Arguments: %s', args)
    install_dependencies(args.plugins_directory)


if __name__ == '__main__':
    main()
