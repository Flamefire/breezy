#    test_upstream.py -- Test getting the upstream source
#    Copyright (C) 2009 Canonical Ltd.
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

# We have a bit of a problem with testing the actual uscan etc. integration,
# so just mock them.

import os

from debian_bundle.changelog import Version

from bzrlib.tests import (
        TestCase,
        TestCaseWithTransport,
        )
from bzrlib.plugins.builddeb.errors import (
        MissingUpstreamTarball,
        PackageVersionNotPresent,
        )
from bzrlib.plugins.builddeb.upstream import (
        AptSource,
        PristineTarSource,
        StackedUpstreamSource,
        UpstreamProvider,
        UpstreamSource,
        UScanSource,
        )
from bzrlib.plugins.builddeb.util import (
        get_parent_dir,
        tarball_name,
        )


class MockSources(object):

    def __init__(self, versions):
        self.restart_called_times = 0
        self.lookup_called_times = 0
        self.lookup_package = None
        self.versions = versions
        self.Version = None

    def Restart(self):
        self.restart_called_times += 1

    def Lookup(self, package):
        self.lookup_called_times += 1
        assert not self.lookup_package or self.lookup_package == package
        self.lookup_package = package
        if self.lookup_called_times <= len(self.versions):
            self.Version = self.versions[self.lookup_called_times-1]
            return True
        else:
            self.Version = None
            return False


class MockAptPkg(object):

    def __init__(self, sources):
        self.init_called_times = 0
        self.get_pkg_source_records_called_times = 0
        self.sources = sources

    def init(self):
        self.init_called_times += 1

    def GetPkgSrcRecords(self):
        self.get_pkg_source_records_called_times += 1
        return self.sources


class MockAptCaller(object):

    def __init__(self, work=False):
        self.work = work
        self.called = 0
        self.package = None
        self.version_str = None
        self.target_dir = None

    def call(self, package, version_str, target_dir):
        self.package = package
        self.version_str = version_str
        self.target_dir = target_dir
        self.called += 1
        return self.work


class AptSourceTests(TestCase):

    def test_get_apt_command_for_source(self):
        self.assertEqual("apt-get source -y --only-source --tar-only "
                "apackage=someversion",
                AptSource()._get_command("apackage", "someversion"))

    def test_apt_provider_no_package(self):
        caller = MockAptCaller()
        sources = MockSources([])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.get_specific_version,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(1, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_wrong_version(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.get_specific_version,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_right_version(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        src.get_specific_version("apackage", "0.2", "target", 
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command works.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)

    def test_apt_provider_right_version_command_fails(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.get_specific_version,
            "apackage", "0.2", "target", 
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command fails.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)


class RecordingSource(object):

    def __init__(self, succeed):
        self._succeed = succeed
        self._specific_versions = []

    def get_specific_version(self, package, version, target_dir):
        self._specific_versions.append((package, version, target_dir))
        if not self._succeed:
            raise PackageVersionNotPresent(package, version, self)


class StackedUpstreamSourceTests(TestCase):

    def test_first_wins(self):
        a = RecordingSource(False)
        b = RecordingSource(True)
        c = RecordingSource(False)
        stack = StackedUpstreamSource([a, b, c])
        stack.get_specific_version("mypkg", "1.0", "bla")
        self.assertEquals([("mypkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("mypkg", "1.0", "bla")], a._specific_versions)
        self.assertEquals([], c._specific_versions)

    def test_none(self):
        a = RecordingSource(False)
        b = RecordingSource(False)
        stack = StackedUpstreamSource([a, b])
        self.assertRaises(PackageVersionNotPresent, 
                stack.get_specific_version, "pkg", "1.0", "bla")
        self.assertEquals([("pkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("pkg", "1.0", "bla")], a._specific_versions)


class UScanSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(UScanSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_export_watchfile_none(self):
        src = UScanSource(self.tree, False)
        self.assertEquals(None, src._export_watchfile())

    def test_export_watchfile_larstiq(self):
        src = UScanSource(self.tree, True)
        self.build_tree(['watch'])
        self.assertEquals(None, src._export_watchfile())
        self.tree.add(['watch'])
        self.assertTrue(src._export_watchfile() is not None)

    def test_export_watchfile(self):
        src = UScanSource(self.tree, False)
        self.build_tree(['debian/', 'debian/watch'])
        self.assertEquals(None, src._export_watchfile())
        self.tree.smart_add(['debian/watch'])
        self.assertTrue(src._export_watchfile() is not None)
