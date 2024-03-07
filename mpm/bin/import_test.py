import argparse
import logging
import sys
from ..api import import_plugin

logger = logging.getLogger(__name__)

def parse_args(args=None):
    """Parses command-line arguments, returns the parsed arguments."""
    # The original code had `args = sys.argv` which includes the script name as the first argument.
    # Typically, when parsing arguments, you'd exclude the script name which `sys.argv[1:]` does.
    # `sys.argv[1:]` is also the default behavior if `args` is not provided to `parser.parse_args()`.
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(description='MicroDrop plugin import test')
    parser.add_argument('package_name', help='Plugin Conda package name')
    parser.add_argument('-a', '--include-available', action='store_true',
                        help='Include all available plugins (not just enabled ones).')

    parsed_args = parser.parse_args(args)
    return parsed_args

def main(cli_args=None):
    parsed_args = parse_args(cli_args)
    logger.debug('Arguments: %s', parsed_args)
    import_plugin(parsed_args.package_name, include_available=parsed_args.include_available)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
