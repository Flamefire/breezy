# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test the GitDir class"""

from dulwich.repo import Repo as GitRepo
import os

from bzrlib import (
    bzrdir,
    errors,
    urlutils,
    )
from bzrlib.tests import TestSkipped

from bzrlib.plugins.git import (
    dir,
    tests,
    workingtree,
    )


class TestGitDir(tests.TestCaseInTempDir):

    def test_get_head_branch_reference(self):
        GitRepo.init(".")

        gd = bzrdir.BzrDir.open('.')
        self.assertEquals(
            "%s,ref=refs/heads/master" %
                urlutils.local_path_to_url(os.path.abspath(".")),
            gd.get_branch_reference())

    def test_open_existing(self):
        GitRepo.init(".")

        gd = bzrdir.BzrDir.open('.')
        self.assertIsInstance(gd, dir.LocalGitDir)

    def test_open_workingtree(self):
        GitRepo.init(".")

        gd = bzrdir.BzrDir.open('.')
        raise TestSkipped
        wt = gd.open_workingtree()
        self.assertIsInstance(wt, workingtree.GitWorkingTree)

    def test_open_workingtree_bare(self):
        GitRepo.init_bare(".")

        gd = bzrdir.BzrDir.open('.')
        self.assertRaises(errors.NoWorkingTree, gd.open_workingtree)


class TestGitDirFormat(tests.TestCase):

    def setUp(self):
        super(TestGitDirFormat, self).setUp()
        self.format = dir.LocalGitControlDirFormat()

    def test_get_format_description(self):
        self.assertEquals("Local Git Repository",
                          self.format.get_format_description())

    def test_eq(self):
        format2 = dir.LocalGitControlDirFormat()
        self.assertEquals(self.format, format2)
        self.assertEquals(self.format, self.format)
        bzr_format = bzrdir.format_registry.make_bzrdir("default")
        self.assertNotEquals(self.format, bzr_format)

