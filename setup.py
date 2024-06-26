import platform
import sys

import setuptools as st
sys.path.insert(0, '.')

install_requires = ['microdrop-libs',
                    'progressbar2', 'pyyaml', 'si-prefix>=0.4.post3']

if platform.system() == 'Windows':
    install_requires += ['pywin32']

st.setup(name='microdrop-plugin-manager',
         version="0.8.8.alpha",
         description='MicroDrop plugin manager.',
         keywords='',
         author='Christian Fobel',
         author_email='christian@fobel.net',
         url='https://github.com/wheeler-microfluidics/mpm',
         license='BSD',
         packages=['mpm', ],
         # Install data listed in `MANIFEST.in`
         include_package_data=True,
         entry_points={'console_scripts': ['mpm = mpm.bin:main']})
