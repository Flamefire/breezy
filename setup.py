#!/usr/bin/env python2.4

bzr_plugin_name = 'stats'

bzr_plugin_version = (0, 0, 1, 'dev', 0)

bzr_commands = ['credits', 'committer-statistics', 'ancestor-growth']

if __name__ == '__main__':
    from distutils.core import setup

    version_string = ".".join([str(v) for v in bzr_plugin_version[:3]])

    setup(name='bzr-stats',
          description='Statistics plugin for Bazaar',
          keywords='plugin bzr stats',
          version=version_string,
          license='GPL',
          author='John Arbash Meinel',
          author_email="john@arbash-meinel.com",
          url="http://launchpad.net/bzr-stats",
          long_description="""
          Simple statistics plugin for Bazaar.
          """,
          package_dir={'bzrlib.plugins.stats':'.'},
          packages=['bzrlib.plugins.stats']
          )
