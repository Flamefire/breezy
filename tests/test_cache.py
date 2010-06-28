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

from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    )

import os
import stat

from bzrlib.inventory import (
    InventoryFile,
    InventoryDirectory,
    ROOT_ID,
    )

from bzrlib.revision import (
    Revision,
    )

from bzrlib.tests import (
    TestCase,
    TestCaseInTempDir,
    UnavailableFeature,
    )
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.plugins.git.cache import (
    DictBzrGitCache,
    IndexBzrGitCache,
    SqliteBzrGitCache,
    TdbBzrGitCache,
    )

class TestGitShaMap:

    def _get_test_commit(self):
        c = Commit()
        c.committer = "Jelmer <jelmer@samba.org>"
        c.commit_time = 0
        c.commit_timezone = 0
        c.author = "Jelmer <jelmer@samba.org>"
        c.author_time = 0
        c.author_timezone = 0
        c.message = "Teh foo bar"
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        return c

    def test_commit(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        c = self._get_test_commit()
        updater.add_object(c, None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEquals(
            ("commit", ("myrevid", "cc9462f7f8263ef5adfbeff2fb936bb36b504cba")),
            self.map.lookup_git_sha(c.id))
        self.assertEquals(c.id, self.map.lookup_commit("myrevid"))

    def test_lookup_notfound(self):
        self.assertRaises(KeyError,
            self.map.lookup_git_sha, "5686645d49063c73d35436192dfc9a160c672301")

    def test_blob(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        updater.add_object(self._get_test_commit(), None)
        b = Blob()
        b.data = "TEH BLOB"
        ie = InventoryFile("myfileid", "somename", ROOT_ID)
        ie.revision = "myrevid"
        updater.add_object(b, ie)
        updater.finish()
        self.map.commit_write_group()
        self.assertEquals(
            ("blob", ("myfileid", "myrevid")),
            self.map.lookup_git_sha(b.id))
        self.assertEquals(b.id,
            self.map.lookup_blob_id("myfileid", "myrevid"))

    def test_tree(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        updater.add_object(self._get_test_commit(), None)
        t = Tree()
        t.add(stat.S_IFREG, "somename", Blob().id)
        ie = InventoryDirectory("fileid", "myname", ROOT_ID)
        ie.revision = "irrelevant"
        updater.add_object(t, ie)
        updater.finish()
        self.map.commit_write_group()
        self.assertEquals(("tree", ("fileid", "myrevid")),
            self.map.lookup_git_sha(t.id))
        # It's possible for a backend to not implement lookup_tree
        try:
            self.assertEquals(t.id,
                self.map.lookup_tree_id("fileid", "myrevid"))
        except NotImplementedError:
            pass

    def test_revids(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        c = self._get_test_commit()
        updater.add_object(c, None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEquals(["myrevid"], list(self.map.revids()))

    def test_missing_revisions(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        c = self._get_test_commit()
        updater.add_object(c, None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEquals(set(["lala", "bla"]),
            set(self.map.missing_revisions(["myrevid", "lala", "bla"])))


class DictGitShaMapTests(TestCase,TestGitShaMap):

    def setUp(self):
        TestCase.setUp(self)
        self.cache = DictBzrGitCache()
        self.map = self.cache.idmap


class SqliteGitShaMapTests(TestCaseInTempDir,TestGitShaMap):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.cache = SqliteBzrGitCache(os.path.join(self.test_dir, 'foo.db'))
        self.map = self.cache.idmap


class TdbGitShaMapTests(TestCaseInTempDir,TestGitShaMap):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        try:
            self.cache = TdbBzrGitCache(os.path.join(self.test_dir, 'foo.tdb'))
        except ImportError:
            raise UnavailableFeature("Missing tdb")
        self.map = self.cache.idmap


class IndexGitShaMapTests(TestCaseInTempDir,TestGitShaMap):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        transport = get_transport(self.test_dir)
        transport.mkdir("index")
        self.cache = IndexBzrGitCache(transport)
        self.map = self.cache.idmap
