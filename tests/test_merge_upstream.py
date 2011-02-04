#    test_merge_upstream.py -- Testsuite for builddeb's upstream merging.
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

try:
    from debian.changelog import Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version

from bzrlib.tests import TestCase

from bzrlib.plugins.builddeb.merge_upstream import (
    upstream_merge_changelog_line,
    package_version,
    )


class TestPackageVersion(TestCase):

  def test_simple_debian(self):
    self.assertEquals(Version("1.2-1"),
        package_version("1.2", "debian"))

  def test_simple_ubuntu(self):
    self.assertEquals(Version("1.2-0ubuntu1"),
        package_version("1.2", "ubuntu"))

  def test_debian_with_dash(self):
    self.assertEquals(Version("1.2-0ubuntu1-1"),
        package_version("1.2-0ubuntu1", "debian"))

  def test_ubuntu_with_dash(self):
    self.assertEquals(Version("1.2-1-0ubuntu1"),
        package_version("1.2-1", "ubuntu"))

  def test_ubuntu_with_epoch(self):
    self.assertEquals(Version("3:1.2-1-0ubuntu1"),
        package_version("1.2-1", "ubuntu", "3"))


class UpstreamMergeChangelogLineTests(TestCase):

    def test_release(self):
        self.assertEquals("New upstream release.", upstream_merge_changelog_line("1.0"))

    def test_bzr_snapshot(self):
        self.assertEquals("New upstream snapshot.",
            upstream_merge_changelog_line("1.0+bzr3"))

    def test_git_snapshot(self):
        self.assertEquals("New upstream snapshot.",
            upstream_merge_changelog_line("1.0~git20101212"))

    def test_plus(self):
        self.assertEquals("New upstream release.",
            upstream_merge_changelog_line("1.0+dfsg1"))
