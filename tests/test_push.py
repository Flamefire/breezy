# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.branch import Branch, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.errors import AlreadyBranchError, DivergedBranches
from bzrlib.inventory import Inventory
from bzrlib.repository import Repository
from bzrlib.tests import TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

import os
import format
import svn.core
from commit import push
from repository import MAPPING_VERSION, SVN_PROP_BZR_REVISION_ID
from revids import generate_svn_revision_id
from tests import TestCaseWithSubversionRepository

class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.svndir = BzrDir.open("sc")
        os.mkdir("dc")
        self.bzrdir = self.svndir.sprout("dc")

    def test_empty(self):
        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)
        self.assertEqual(svnbranch.revision_history(),
                         bzrbranch.revision_history())

    def test_child(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)

    def test_diverged(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        svndir = BzrDir.open("sc")

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          svndir.open_branch().pull,
                          self.bzrdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.bzrdir.open_workingtree()
        newid = wt.commit(message="Commit from Bzr")

        svnbranch = self.svndir.open_branch()
        svnbranch.pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        self.assertEquals(newid, svnbranch.last_revision())
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertEqual(newid, inv[inv.path2id('foo/bla')].revision)
        self.assertEqual(wt.branch.last_revision(),
          repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.svndir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree(repos.generate_revision_id(2, "", 
                                "none")).get_file_text(inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.svndir.open_branch().last_revision())

    def test_empty_file(self):
        self.build_tree({'dc/file': ''})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.svndir.open_branch().last_revision())

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                         repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.svndir.open_branch().last_revision())

        self.bzrdir.open_branch().pull(self.svndir.open_branch())

        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.bzrdir.open_branch().last_revision())

    def test_branch_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        os.mkdir("b")
        repos = self.svndir.sprout("b")

        self.assertEqual(Branch.open("dc").revision_history(), 
                         Branch.open("b").revision_history())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        self.assertEqual("Commit from Bzr",
          repos.get_revision(repos.generate_revision_id(2, "", "none")).message)

    def test_commit_set_revid(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr", rev_id="some-rid")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        self.client_update("sc")
        self.assertEqual("3 some-rid\n", 
                self.client_get_prop("sc", SVN_PROP_BZR_REVISION_ID+"none"))

    def test_commit_check_rev_equal(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        rev1 = self.svndir.find_repository().get_revision(wt.branch.last_revision())
        rev2 = self.bzrdir.find_repository().get_revision(wt.branch.last_revision())

        self.assertEqual(rev1.committer, rev2.committer)
        self.assertEqual(rev1.timestamp, rev2.timestamp)
        self.assertEqual(rev1.timezone, rev2.timezone)
        self.assertEqual(rev1.properties, rev2.properties)
        self.assertEqual(rev1.message, rev2.message)
        self.assertEqual(rev1.revision_id, rev2.revision_id)

    def test_multiple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'dc/file': 'data2', 'dc/adir': None})
        wt.add('adir')
        wt.commit(message="Another commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()

        self.assertEqual(repos.generate_revision_id(3, "", "none"), 
                        self.svndir.open_branch().last_revision())

        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertFalse(inv.has_filename('adir'))

        inv = repos.get_inventory(repos.generate_revision_id(3, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(inv.has_filename('adir'))

        self.assertEqual(self.svndir.open_branch().revision_history(),
                         self.bzrdir.open_branch().revision_history())

        self.assertEqual(wt.branch.last_revision(), 
                repos.generate_revision_id(3, "", "none"))
        self.assertEqual(
                wt.branch.repository.get_ancestry(wt.branch.last_revision()), 
                repos.get_ancestry(wt.branch.last_revision()))

    def test_multiple_diverged(self):
        oc_url = self.make_client("o", "oc")

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'oc/file': 'data2', 'oc/adir': None})
        self.client_add("oc/file")
        self.client_add("oc/adir")
        self.client_commit("oc", "Another commit from Bzr")

        self.assertRaises(DivergedBranches, 
                lambda: Branch.open(oc_url).pull(self.bzrdir.open_branch()))

    def test_different_branch_path(self):
        # A       ,> C
        # \ -> B /
        self.build_tree({'sc/trunk/foo': "data", 'sc/branches': None})
        self.client_add("sc/trunk")
        self.client_add("sc/branches")
        self.client_commit("sc", "foo")

        self.client_copy('sc/trunk', 'sc/branches/mybranch')
        self.build_tree({'sc/branches/mybranch/foo': "data2"})
        self.client_commit("sc", "add branch")

        self.svndir = BzrDir.open("sc/branches/mybranch")
        os.mkdir("mybranch")
        self.bzrdir = self.svndir.sprout("mybranch")

        self.build_tree({'mybranch/foo': 'bladata'})
        wt = self.bzrdir.open_workingtree()
        revid = wt.commit(message="Commit from Bzr")
        push(Branch.open("sc/trunk"), wt.branch, 
             wt.branch.revision_history()[-2])
        mutter('log %r' % self.client_log("sc/trunk")[4][0])
        self.assertEquals('M',
            self.client_log("sc/trunk")[4][0]['/trunk'].action)
        push(Branch.open("sc/trunk"), wt.branch, wt.branch.last_revision())
        mutter('log %r' % self.client_log("sc/trunk")[5][0])
        self.assertEquals("/branches/mybranch", 
            self.client_log("sc/trunk")[5][0]['/trunk'].copyfrom_path)

class PushNewBranchTests(TestCaseWithSubversionRepository):
    def test_single_revision(self):
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        newtree = newbranch.repository.revision_tree(revid)
        bzrwt.lock_read()
        self.assertEquals(bzrwt.inventory.root.file_id,
                          newtree.inventory.root.file_id)
        bzrwt.unlock()
        self.assertEquals(revid, newbranch.last_revision())
        self.assertEquals([revid], newbranch.revision_history())

    def test_repeat(self):
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid, newbranch.last_revision())
        self.assertEquals([revid], newbranch.revision_history())
        self.build_tree({'c/test': "Tour de France"})
        bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        self.assertRaises(AlreadyBranchError, newdir.import_branch, 
                          bzrwt.branch)

    def test_multiple(self):
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid1 = bzrwt.commit("Do a commit")
        self.build_tree({'c/test': "Tour de France"})
        revid2 = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())

    def test_multiple_part_exists(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/myfile': "data", 'dc/branches': None})
        self.client_add('dc/trunk')
        self.client_add('dc/branches')
        self.client_commit("dc", "Message")
        svnrepos = Repository.open(repos_url)
        os.mkdir("c")
        bzrdir = BzrDir.open(repos_url+"/trunk").sprout("c")
        bzrwt = bzrdir.open_workingtree()
        self.build_tree({'c/myfile': "Tour"})
        revid1 = bzrwt.commit("Do a commit")
        self.build_tree({'c/myfile': "Tour de France"})
        revid2 = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/branches/mybranch")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([
            svnrepos.generate_revision_id(1, "trunk", "trunk0") 
            , revid1, revid2], newbranch.revision_history())

    def test_complex_rename(self):
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file")
        bzrwt.rename_one("registry", "registry.moved")
        os.unlink("c/registry.moved/generic.c")
        bzrwt.remove("registry.moved/generic.c")
        self.build_tree({'c/registry/generic.c': "bla"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid2 = bzrwt.commit("Do some funky things")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())
        tree = newbranch.repository.revision_tree(revid2)
        mutter("inventory: %r" % tree.inventory.entries())
        delta = tree.changes_from(bzrwt)
        self.assertFalse(delta.has_changed())
        self.assertTrue(tree.inventory.has_filename("registry"))
        self.assertTrue(tree.inventory.has_filename("registry.moved"))
        self.assertTrue(tree.inventory.has_filename("registry/generic.c"))
        self.assertFalse(tree.inventory.has_filename("registry.moved/generic.c"))
        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")
    
    def test_push_non_lhs_parent(self):        
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file", 
                              rev_id="initialrevid")

        # Push first branch into Subversion
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)

        # Should create dc/trunk
        self.client_update("dc")

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_copy("dc/trunk", "dc/branches/foo")
        self.client_commit("dc", "Copy branches")
        self.client_update("dc")

        self.build_tree({'dc/branches/foo/registry/generic.c': "France"})
        merge_revno = self.client_commit("dc", "Change copied branch")[0]
        merge_revid = newdir.find_repository().generate_revision_id(merge_revno, "branches/foo", "trunk0")

        self.build_tree({'c/registry/generic.c': "de"})
        revid2 = bzrwt.commit("Change something", rev_id="changerevid")

        # Merge 
        self.build_tree({'c/registry/generic.c': "France"})
        bzrwt.add_pending_merge(merge_revid)
        revid3 = bzrwt.commit("Merge something", rev_id="mergerevid")

        trunk = Branch.open(repos_url + "/branches/foo")
        trunk.pull(bzrwt.branch)

        self.assertEquals([revid1, revid2, revid3], trunk.revision_history())
        self.client_update("dc")
        self.assertEquals(
                '1 initialrevid\n2 changerevid\n3 mergerevid\n',
                self.client_get_prop("dc/branches/foo", SVN_PROP_BZR_REVISION_ID+"trunk0"))

    def test_complex_replace_dir(self):
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add(["registry"], ["origdir"])
        bzrwt.add(["registry/generic.c"], ["file"])
        revid1 = bzrwt.commit("Add initial directory + file")

        bzrwt.remove('registry/generic.c')
        bzrwt.remove('registry')
        bzrwt.add(["registry"], ["newdir"])
        bzrwt.add(["registry/generic.c"], ["file"])
        revid2 = bzrwt.commit("Do some funky things")

        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())

        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")

    def test_push_unnecessary_merge(self):        
        from bzrlib.debug import debug_flags
        debug_flags.add('transport')
        debug_flags.add('commit')
        repos_url = self.make_client("a", "dc")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file", 
                              rev_id="initialrevid")

        # Push first branch into Subversion
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)

        # Should create dc/trunk
        self.client_update("dc")

        self.assertTrue(os.path.exists("dc/trunk/registry/generic.c"))
        self.build_tree({'dc/trunk/registry/generic.c': "DE"})
        self.client_commit("dc", "Change copied branch")
        self.client_update("dc")
        merge_revid = newdir.find_repository().generate_revision_id(2, "trunk", "trunk0")

        # Merge 
        self.build_tree({'c/registry/generic.c': "DE"})
        bzrwt.add_pending_merge(merge_revid)
        revid2 = bzrwt.commit("Merge something", rev_id="mergerevid")

        trunk = Branch.open(repos_url + "/trunk")
        trunk.pull(bzrwt.branch)

        self.assertEquals([revid1, revid2], trunk.revision_history())
        self.client_update("dc")
        self.assertEquals(
                '1 initialrevid\n2 mergerevid\n',
                self.client_get_prop("dc/trunk", SVN_PROP_BZR_REVISION_ID+"trunk0"))


