import argparse
import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


def parse_args(args=None):
    """
    Parses arguments, returns ``(options, args)``.
    .. versionchanged:: 0.24.1
        Fix handling of optional :data:`args`.
    """
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(description='MicroDrop plugin Conda recipe builder')
    parser.add_argument('-s', '--source-dir', type=Path, nargs='?')
    parser.add_argument('-t', '--target-dir', type=Path, nargs='?')
    parser.add_argument('-p', '--package-name', nargs='?')
    # Use `-V` for version (from [common Unix flags][1]).
    #
    # [1]: https://unix.stackexchange.com/a/108141/187716
    parser.add_argument('-V', '--version-number', nargs='?')

    parsed_args = parser.parse_args(args)
    if not parsed_args.source_dir:
        parsed_args.source_dir = Path(os.environ['SRC_DIR'])
    if not parsed_args.target_dir:
        prefix_dir = Path(os.environ['PREFIX'])
        # Extract module name from Conda package name.
        #
        # For example, the module name for a package named
        # `microdrop.droplet_planning_plugin` would be
        # `droplet_planning_plugin`.
        module_name = os.environ['PKG_NAME'].split('.')[-1].replace('-', '_')
        parsed_args.target_dir = prefix_dir / 'share' / 'microdrop' / 'plugins' / 'available' / module_name
    if not parsed_args.package_name:
        parsed_args.package_name = os.environ['PKG_NAME']

    return parsed_args


def build(source_dir, target_dir, package_name=None, version_number=None):
    """
        Create a release of a MicroDrop plugin source directory in the target
        directory path.
        Skip the following patterns:
         - ``bld.bat``
         - ``.conda-recipe/*``
         - ``.git/*``
        .. versionchanged:: 0.24.1
            Remove temporary archive after extraction.
            Change directory into source directory before running ``git archive``.
        .. versionchanged:: 0.25
            Add optional :data:`version_number` argument.
        Parameters
        ----------
        source_dir : str
            Source directory.
        target_dir : str
            Target directory.
        package_name : str, optional
            Name of plugin Conda package (defaults to name of :data:`target_dir`).
        version_number : str, optional
            Package version number.
            If not specified, assume version package exposes version using
            `versioneer <https://github.com/warner/python-versioneer>`_.
    """
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    source_archive = source_dir / f'{source_dir.name}.zip'
    if package_name is None:
        package_name = target_dir.name
    logger.info(f'Source directory: {source_dir}')
    logger.info(f'Source archive: {source_archive}')
    logger.info(f'Target directory: {target_dir}')
    logger.info(f'Package name: {package_name}')

    # Export git archive, which substitutes version expressions in
    # `_version.py` to reflect the state (i.e., revision and tag info) of the
    # git repository.
    original_dir = Path.cwd()
    try:
        os.chdir(source_dir)
        subprocess.check_call(['git', 'archive', '-o', source_archive, 'HEAD'], shell=True)
    finally:
        os.chdir(original_dir)

    # Extract exported git archive to Conda MicroDrop plugins directory.
    with zipfile.ZipFile(source_archive, 'r') as zip_ref:
        zip_ref.extractall(target_dir)
    # Extraction is complete.  Remove temporary archive.
    source_archive.unlink()

    # Delete Conda build recipe from installed package.
    (target_dir / '.conda-recipe').rmdir()
    # Delete Conda build recipe from installed package.
    for p in target_dir.glob('.git*'):
        p.unlink()

    try:
        os.chdir(source_dir)
        if version_number is None:
            import _version as v
            version_info = {'version': v.get_versions()['version'], 'versioneer': v.get_versions()}
        else:
            version_info = {'version': version_number}
    finally:
        os.chdir(original_dir)

    properties = {'package_name': package_name, 'plugin_name': str(target_dir.name)}
    properties.update(version_info)

    with (target_dir / 'properties.yml').open('w') as properties_yml:
        yaml.dump(properties, properties_yml, default_flow_style=False)


def main(args=None):
    if args is None:
        args = parse_args()
    logger.debug(f'Arguments: {args}')
    build(args.source_dir, args.target_dir, package_name=args.package_name, version_number=args.version_number)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
