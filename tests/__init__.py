#    __init__.py -- Testsuite for builddeb
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import shutil
import subprocess
import tarfile
import zipfile

from copy import deepcopy
import doctest
import os
from unittest import TestSuite

from debian_bundle.changelog import Version, Changelog

from bzrlib.tests import TestUtil, adapt_modules, TestCaseWithTransport

from bzrlib.plugins.builddeb.tests import blackbox


def make_new_upstream_dir(dir):
    def _make_upstream_dir():
        os.rename('package-0.2', dir)
    return _make_upstream_dir


def make_new_upstream_tarball(tarball):
    def _make_upstream_tarball():
        tar = tarfile.open(tarball, 'w:gz')
        try:
            tar.add('package-0.2')
        finally:
            tar.close()
        shutil.rmtree('package-0.2')
    return _make_upstream_tarball


def make_new_upstream_tarball_bz2(tarball):
    def _make_upstream_tarball():
        tar = tarfile.open(tarball, 'w:bz2')
        try:
            tar.add('package-0.2')
        finally:
            tar.close()
        shutil.rmtree('package-0.2')
    return _make_upstream_tarball


def make_new_upstream_tarball_zip(tarball):
    def _make_upstream_tarball():
        zip = zipfile.ZipFile(tarball, 'w')
        try:
            zip.writestr('package-0.2/', '')
            for (dirpath, dirnames, names) in os.walk('package-0.2'):
                for dir in dirnames:
                    zip.writestr(os.path.join(dirpath, dir, ''), '')
                for name in names:
                    zip.write(os.path.join(dirpath, name))
        finally:
            zip.close()
        shutil.rmtree('package-0.2')
    return _make_upstream_tarball

def make_new_upstream_tarball_bare(tarball):
    def _make_upstream_tarball():
        tar = tarfile.open(tarball, 'w')
        try:
            tar.add('package-0.2')
        finally:
            tar.close()
        shutil.rmtree('package-0.2')
    return _make_upstream_tarball

tarball_functions = [('dir', make_new_upstream_dir, '../package-0.2'),
                     ('.tar.gz', make_new_upstream_tarball,
                      '../package-0.2.tar.gz'),
                     ('.tar.bz2', make_new_upstream_tarball_bz2,
                      '../package-0.2.tar.bz2'),
                     ('.zip', make_new_upstream_tarball_zip,
                      '../package-0.2.zip'),
                     ('.tar', make_new_upstream_tarball_bare,
                      '../package-0.2.tar'),
                     ]


class RepackTarballAdaptor(object):

    def adapt(self, test):
        result = TestSuite()
        for (name, function, source) in tarball_functions:
            new_test = deepcopy(test)
            source = os.path.basename(source)
            new_test.build_tarball = function(source)
            new_test.old_tarball = source
            def make_new_id():
                new_id = '%s(%s)' % (test.id(), name)
                return lambda: new_id
            new_test.id = make_new_id()
            result.addTest(new_test)
        return result


def test_suite():
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_builder',
            'test_commit_message',
            'test_config',
            'test_hooks',
            'test_import_dsc',
            'test_merge_upstream',
            'test_repack_tarball_extra',
            'test_revspec',
            'test_source_distiller',
            'test_upstream',
            'test_util',
            ]
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i)
                                            for i in testmod_names]))

    doctest_mod_names = [
             'changes',
             'config'
             ]
    for mod in doctest_mod_names:
        suite.addTest(doctest.DocTestSuite("bzrlib.plugins.builddeb." + mod))

    adapt_modules(['%s.test_repack_tarball' % __name__],
                  RepackTarballAdaptor(), loader, suite)

    packages_to_test = [
             blackbox,
             ]

    for package in packages_to_test:
        suite.addTest(package.test_suite())

    return suite

class BuilddebTestCase(TestCaseWithTransport):

    package_name = 'test'
    package_version = Version('0.1-1')
    upstream_version = property(lambda self: \
                                self.package_version.upstream_version)

    def make_changelog(self, version=None):
        if version is None:
            version = self.package_version
        c = Changelog()
        c.new_block()
        c.version = Version(version)
        c.package = self.package_name
        c.distributions = 'unstable'
        c.urgency = 'low'
        c.author = 'James Westby <jw+debian@jameswestby.net>'
        c.date = 'Thu,  3 Aug 2006 19:16:22 +0100'
        c.add_change('')
        c.add_change('  *  test build')
        c.add_change('')
        return c

    def write_changelog(self, changelog, filename):
        f = open(filename, 'w')
        changelog.write_to_open_file(f)
        f.close()

    def check_tarball_contents(self, tarball, expected, basedir=None,
                             skip_basedir=False, mode=None):
        """Test that the tarball has certain contents.

        Test that the tarball has exactly expected contents. The basedir
        is checked for and prepended if it is not None. The mode is the mode
        used in tarfile.open defaults to r:gz. If skip_basedir is True and
        basedir is not None then the basedir wont be tested for itself.
        """
        if basedir is None:
            real_expected = expected[:]
        else:
            if skip_basedir:
                real_expected = []
            else:
                real_expected = [basedir]
        for item in expected:
            real_expected.append(os.path.join(basedir, item).rstrip("/"))
        extras = []
        tar = tarfile.open(tarball, 'r:gz')
        try:
            for tarinfo in tar:
                if tarinfo.name in real_expected:
                    index = real_expected.index(tarinfo.name)
                    del real_expected[index:index+1]
                else:
                    extras.append(tarinfo.name)

            if len(real_expected) > 0:
                self.fail("Files not found in %s: %s"
                        % (tarball, ", ".join(real_expected)))
            if len(extras) > 0:
                self.fail("Files not expected to be found in %s: %s"
                        % (tarball, ", ".join(extras)))
        finally:
            tar.close()


class SourcePackageBuilder(object):
    """An interface to ease building source packages.

    >>> builder = SourcePackageBuilder("package", Version("0.1-1"))
    >>> builder.add_upstream_file("foo")
    >>> builder.add_debian_file("debian/copyright")
    >>> builder.add_default_control()
    >>> builder.build()
    >>> builder.new_version(Version("0.2-1"))
    >>> builder.add_upstream_file("bar")
    >>> builder.remove_upstream_file("foo")
    >>> builder.build()
    >>> builder.dsc_name()
    """

    def __init__(self, name, version, native=False):
        self.upstream_files = {}
        self.debian_files = {}
        self.name = name
        self.native = native
        self._cl = Changelog()
        self.new_version(version)

    def add_upstream_file(self, name, content=None):
        self.add_upstream_files([(name, content)])

    def add_upstream_files(self, files):
        for new_file in files:
            self.upstream_files[new_file[0]] = new_file[1]

    def remove_upstream_file(self, filename):
        del self.upstream_files[filename]

    def add_debian_file(self, name, content=None):
        self.add_debian_files([(name, content)])

    def add_debian_files(self, files):
        for new_file in files:
            self.debian_files[new_file[0]] = new_file[1]

    def remove_debian_file(self, filename):
        del self.debian_files[filename]

    def add_default_control(self):
        text = """Source: %s\nSection: misc\n""" % self.name
        text += "Priority: optional\n"
        text += "Maintainer: Maintainer <nobody@ubuntu.com>\n"
        self.add_debian_file("debian/control", text)

    def new_version(self, version, change_text=None):
        self._cl.new_block(package=self.name, version=version,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org>",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        if change_text is None:
            self._cl.add_change("  * foo")
        else:
            self._cl.add_change(change_text)

    def dsc_name(self):
        return "%s_%s.dsc" % (self.name, str(self._cl.version))

    def tar_name(self):
        if self.native:
            return "%s_%s.tar.gz" % (self.name, str(self._cl.version))
        return "%s_%s.orig.tar.gz" % (self.name,
                str(self._cl.version.upstream_version))

    def diff_name(self):
        assert not self.native, "Can't have a diff with a native package"
        return "%s_%s.diff.gz" % (self.name, str(self._cl.version))

    def changes_name(self):
        return "%s_%s_source.changes" % (self.name, str(self._cl.version))

    def _make_files(self, files_list, basedir):
        for (path, content) in files_list.items():
            dirname = os.path.dirname(path)
            if dirname is not None and dirname != "":
                if not os.path.exists(os.path.join(basedir, dirname)):
                    os.makedirs(os.path.join(basedir, dirname))
            f = open(os.path.join(basedir, path), 'wb')
            try:
                if content is None:
                    content = ''
                f.write(content)
            finally:
                f.close()

    def basedir(self):
        return self.name + "-" + str(self._cl.version.upstream_version)

    def _make_base(self):
        basedir = self.basedir()
        os.mkdir(basedir)
        self._make_files(self.upstream_files, basedir)
        return basedir

    def build(self):
        basedir = self._make_base()
        if not self.native:
            orig_basedir = basedir + ".orig"
            shutil.copytree(basedir, orig_basedir)
            cmd = "dpkg-source -sa -b %s" % (basedir)
            if os.path.exists("%s_%s.orig.tar.gz"
                    % (self.name, self._cl.version.upstream_version)):
                cmd = "dpkg-source -ss -b %s" % (basedir)
        else:
            cmd = "dpkg-source -sn -b %s" % (basedir)
        self._make_files(self.debian_files, basedir)
        self._make_files({"debian/changelog": str(self._cl)}, basedir)
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        ret = proc.wait()
        assert ret == 0, "dpkg-source failed, output:\n%s\n%s" % \
                (proc.stdout.read(), proc.stderr.read())
        cmd = "dpkg-genchanges -S > ../%s" % self.changes_name()
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=basedir)
        ret = proc.wait()
        assert ret == 0, "dpkg-genchanges failed, output:\n%s\n%s" % \
                (proc.stdout.read(), proc.stderr.read())
        shutil.rmtree(basedir)
