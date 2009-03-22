# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for GitShaMap."""

from bzrlib.tests import TestCase

from bzrlib.plugins.git.shamap import (
    DictGitShaMap,
    SqliteGitShaMap,
    )

class TestGitShaMap:

    def test_commit(self):
        self.map.add_entry("5686645d49063c73d35436192dfc9a160c672301", 
            "commit", ("myrevid", "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"))
        self.assertEquals(
            ("commit", ("myrevid", "cc9462f7f8263ef5adfbeff2fb936bb36b504cba")),
            self.map.lookup_git_sha("5686645d49063c73d35436192dfc9a160c672301"))

    def test_lookup_notfound(self):
        self.assertRaises(KeyError, 
            self.map.lookup_git_sha, "5686645d49063c73d35436192dfc9a160c672301")
        
    def test_blob(self):
        self.map.add_entry("5686645d49063c73d35436192dfc9a160c672301", 
            "blob", ("myfileid", "myrevid"))
        self.assertEquals(
            ("blob", ("myfileid", "myrevid")),
            self.map.lookup_git_sha("5686645d49063c73d35436192dfc9a160c672301"))

    def test_tree(self):
        self.map.add_entry("5686645d49063c73d35436192dfc9a160c672301", 
            "tree", ("somepath", "myrevid"))
        self.assertEquals(
            ("tree", ("somepath", "myrevid")),
            self.map.lookup_git_sha("5686645d49063c73d35436192dfc9a160c672301"))

    def test_revids(self):
        self.map.add_entry("5686645d49063c73d35436192dfc9a160c672301", 
            "commit", ("myrevid", "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"))
        self.assertEquals(["myrevid"], list(self.map.revids()))


class DictGitShaMapTests(TestCase,TestGitShaMap):

    def setUp(self):
        TestCase.setUp(self)
        self.map = DictGitShaMap()


class SqliteGitShaMapTests(TestCase,TestGitShaMap):

    def setUp(self):
        TestCase.setUp(self)
        self.map = SqliteGitShaMap()

