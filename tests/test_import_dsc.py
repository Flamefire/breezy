#    test_import_dsc.py -- Test importing .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#              (C) 2008 Canonical Ltd.
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

import os
import shutil
import tarfile

try:
    from debian.changelog import Version
    from debian import deb822
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version
    from debian_bundle import deb822

from bzrlib import (
        tests,
        )

from bzrlib.plugins.builddeb.import_dsc import (
        DistributionBranch,
        DistributionBranchSet,
        OneZeroSourceExtractor,
        SOURCE_EXTRACTORS,
        ThreeDotZeroNativeSourceExtractor,
        ThreeDotZeroQuiltSourceExtractor,
        )
from bzrlib.plugins.builddeb.tests import (
        BuilddebTestCase,
        SourcePackageBuilder,
        )


class _PristineTarFeature(tests.Feature):

    def feature_name(self):
        return '/usr/bin/pristine-tar'

    def _probe(self):
        return os.path.exists("/usr/bin/pristine-tar")


PristineTarFeature = _PristineTarFeature()


def write_to_file(filename, contents):
    f = open(filename, 'wb')
    try:
        f.write(contents)
    finally:
        f.close()


class DistributionBranchTests(BuilddebTestCase):

    def setUp(self):
        super(DistributionBranchTests, self).setUp()
        self.tree1 = self.make_branch_and_tree('unstable')
        root_id = self.tree1.path2id("")
        self.up_tree1 = self.make_branch_and_tree('unstable-upstream')
        self.up_tree1.set_root_id(root_id)
        self.db1 = DistributionBranch(self.tree1.branch,
                self.up_tree1.branch, tree=self.tree1,
                pristine_upstream_tree=self.up_tree1)
        self.tree2 = self.make_branch_and_tree('experimental')
        self.tree2.set_root_id(root_id)
        self.up_tree2 = self.make_branch_and_tree('experimental-upstream')
        self.up_tree2.set_root_id(root_id)
        self.db2 = DistributionBranch(self.tree2.branch,
                self.up_tree2.branch, tree=self.tree2,
                pristine_upstream_tree=self.up_tree2)
        self.tree3 = self.make_branch_and_tree('gutsy')
        self.tree3.set_root_id(root_id)
        self.up_tree3 = self.make_branch_and_tree('gutsy-upstream')
        self.up_tree3.set_root_id(root_id)
        self.db3 = DistributionBranch(self.tree3.branch,
                self.up_tree3.branch, tree=self.tree3,
                pristine_upstream_tree=self.up_tree3)
        self.tree4 = self.make_branch_and_tree('hardy')
        self.tree4.set_root_id(root_id)
        self.up_tree4 = self.make_branch_and_tree('hardy-upstream')
        self.up_tree4.set_root_id(root_id)
        self.db4 = DistributionBranch(self.tree4.branch,
                self.up_tree4.branch, tree=self.tree4,
                pristine_upstream_tree=self.up_tree4)
        self.set = DistributionBranchSet()
        self.set.add_branch(self.db1)
        self.set.add_branch(self.db2)
        self.set.add_branch(self.db3)
        self.set.add_branch(self.db4)
        self.fake_md5_1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        self.fake_md5_2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    def assertContentsAre(self, filename, expected_contents):
        f = open(filename)
        try:
          contents = f.read()
        finally:
          f.close()
        self.assertEqual(contents, expected_contents,
                         "Contents of %s are not as expected" % filename)

    def do_commit_with_md5(self, tree, message, md5):
        return tree.commit(message, revprops={"deb-md5":md5})

    def test_create(self):
        db = self.db1
        self.assertNotEqual(db, None)
        self.assertEqual(db.branch, self.tree1.branch)
        self.assertEqual(db.pristine_upstream_branch, self.up_tree1.branch)
        self.assertEqual(db.tree, self.tree1)
        self.assertEqual(db.pristine_upstream_tree, self.up_tree1)

    def test_tag_name(self):
        db = self.db1
        version_no = "0.1-1"
        version = Version(version_no)
        self.assertEqual(db.tag_name(version), version_no)

    def test_tag_version(self):
        db = self.db1
        tree = self.tree1
        version = Version("0.1-1")
        revid = tree.commit("one")
        db.tag_version(version)
        self.assertEqual(tree.branch.tags.lookup_tag(db.tag_name(version)),
                revid)

    def test_tag_upstream_version(self):
        db = self.db1
        tree = self.up_tree1
        version = "0.1"
        revid = tree.commit("one")
        db.tag_upstream_version(version)
        tag_name = db.pristine_upstream_source.tag_name(version)
        self.assertEqual(tree.branch.tags.lookup_tag(tag_name), revid)

    def test_has_version(self):
        db = self.db1
        version = Version("0.1-1")
        self.assertFalse(db.has_version(version))
        self.assertFalse(db.has_version(version, self.fake_md5_1))
        self.do_commit_with_md5(self.tree1, "one", self.fake_md5_1)
        db.tag_version(version)
        self.assertTrue(db.has_version(version))
        self.assertTrue(db.has_version(version, self.fake_md5_1))
        self.assertFalse(db.has_version(version, self.fake_md5_2))
        version = Version("0.1-2")
        self.assertFalse(db.has_version(version))
        self.assertFalse(db.has_version(version, self.fake_md5_1))
        self.assertFalse(db.has_version(version, self.fake_md5_2))

    def test_pristine_upstream_source_has_version(self):
        db = self.db1
        version = "0.1"
        self.assertFalse(db.pristine_upstream_source.has_version("package", version))
        self.assertFalse(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_1)]))
        self.do_commit_with_md5(self.up_tree1, "one", self.fake_md5_1)
        db.tag_upstream_version(version)
        self.assertTrue(db.pristine_upstream_source.has_version("package", version))
        self.assertTrue(db.pristine_upstream_source.has_version("package",
            version, [("foo.tar.gz", None, self.fake_md5_1)]))
        self.assertFalse(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_2)]))
        version = "0.1"
        self.assertTrue(db.pristine_upstream_source.has_version("package", version))
        self.assertTrue(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_1)]))
        self.assertFalse(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_2)]))
        version = "0.2"
        self.assertFalse(db.pristine_upstream_source.has_version("package", version))
        self.assertFalse(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_1)]))
        self.assertFalse(db.pristine_upstream_source.has_version("package", version,
            [("foo.tar.gz", None, self.fake_md5_2)]))

    def test_revid_of_version(self):
        db = self.db1
        tree = self.tree1
        version = Version("0.1-1")
        revid = tree.commit("one")
        db.tag_version(version)
        self.assertEqual(db.revid_of_version(version), revid)

    def test_upstream_version_as_revid(self):
        db = self.db1
        tree = self.up_tree1
        version = "0.1"
        revid = tree.commit("one")
        db.tag_upstream_version(version)
        self.assertEqual(
            db.pristine_upstream_source.version_as_revision("package", version), revid)

    def test_contained_versions(self):
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        version3 = Version("0.1-3")
        version4 = Version("0.1-4")
        version5 = Version("0.1-5")
        self.assertEqual(db.contained_versions([]), ([], []))
        self.assertEqual(db.contained_versions([version1]),
                ([], [version1]))
        self.tree1.commit("one")
        db.tag_version(version1)
        db.tag_version(version3)
        db.tag_version(version4)
        version_list = [version5, version4, version3, version2, version1]
        self.assertEqual(db.contained_versions(version_list),
                ([version4, version3, version1], [version5, version2]))
        self.assertEqual(db.contained_versions([]), ([], []))

    def test_missing_versions(self):
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        version3 = Version("0.1-3")
        version4 = Version("0.1-4")
        version5 = Version("0.1-5")
        self.assertEqual(db.missing_versions([]), [])
        self.assertEqual(db.missing_versions([version1]), [version1])
        self.tree1.commit("one")
        db.tag_version(version1)
        db.tag_version(version3)
        version_list = [version5, version4, version3, version2, version1]
        self.assertEqual(db.missing_versions(version_list),
                [version5, version4])
        self.assertEqual(db.missing_versions([]), [])

    def test_last_contained_version(self):
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        version3 = Version("0.1-3")
        self.assertEqual(db.last_contained_version([]), None)
        self.assertEqual(db.last_contained_version([version1]), None)
        self.tree1.commit("one")
        db.tag_version(version1)
        db.tag_version(version3)
        self.assertEqual(db.last_contained_version([version2]), None)
        self.assertEqual(db.last_contained_version([]), None)
        self.assertEqual(db.last_contained_version([version2, version1]),
                version1)
        self.assertEqual(db.last_contained_version([version3, version2,
                                                    version1]), version3)

    def test_get_parents_first_version(self):
        """If there are no previous versions then there are no parents."""
        db = self.db1
        version1 = Version("0.1-1")
        self.assertEqual(db.get_parents([version1]), [])
        db = self.db2
        self.assertEqual(db.get_parents([version1]), [])

    def test_get_parents_second_version(self):
        """Previous with same upstream should give that as parent."""
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        db.tag_version(version1)
        self.assertEqual(db.get_parents([version2, version1]),
                [(db, version1, revid1)])

    def test_get_parents_merge_from_lesser(self):
        """Merge with same upstream version gives merged as second parent."""
        version1 = Version("0.1-1")
        version2 = Version("0.1-0ubuntu1")
        version3 = Version("0.1-1ubuntu1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        versions = [version3, version1, version2]
        # test is that revid1 is second parent
        self.assertEqual(self.db2.get_parents(versions),
                [(self.db2, version2, revid2),
                (self.db1, version1, revid1)])

    def test_get_parents_merge_from_greater(self):
        """Merge from greater is same as merge from lesser."""
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        versions = [version3, version2, version1]
        # test is that revid2 is second parent
        self.assertEqual(self.db1.get_parents(versions),
                [(self.db1, version1, revid1),
                (self.db2, version2, revid2)])

    def test_get_parents_merge_from_two_lesser(self):
        """Should use greatest lesser when two candidates."""
        version1 = Version("0.1-1")
        version2 = Version("0.1-0ubuntu1")
        version3 = Version("0.1-1ubuntu1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree3.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version1)
        self.db3.tag_version(version2)
        versions = [version3, version1, version2]
        # test is that revid2 and not revid1 is second parent
        self.assertEqual(self.db3.get_parents(versions),
                [(self.db3, version2, revid3),
                (self.db2, version1, revid2)])

    def test_get_parents_merge_from_two_greater(self):
        """Should use least greater when two candidates."""
        version1 = Version("0.1-1")
        version2 = Version("0.1-0ubuntu1")
        version3 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree3.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db3.tag_version(version2)
        versions = [version3, version2, version1]
        # test is that revid2 and not revid3 is second parent
        self.assertEqual(self.db1.get_parents(versions),
                [(self.db1, version1, revid1),
                (self.db2, version2, revid2)])

    def test_get_parents_merge_multiple_from_greater(self):
        """More than two parents correctly ordered."""
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.1-1other1")
        version4 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree3.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db3.tag_version(version3)
        versions = [version4, version3, version2, version1]
        # test is that revid2 is second, revid3 is third
        self.assertEqual(self.db1.get_parents(versions),
                [(self.db1, version1, revid1), (self.db2, version2, revid2),
                (self.db3, version3, revid3)])

    def test_get_parents_sync_when_diverged(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree1.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db1.tag_version(version3)
        versions = [version3, version2, version1]
        # This is a sync, but we have diverged, so we should
        # get two parents, the last ubuntu upload,
        # and the Debian upload as the second parent.
        self.assertEqual(self.db2.get_parents(versions),
                [(self.db2, version2, revid2),
                (self.db1, version3, revid3)])

    def test_get_parents_skipped_version(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        version3 = Version("0.1-2ubuntu1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        versions = [version3, version2, version1]
        self.assertEqual(self.db2.get_parents(versions),
                [(self.db2, version2, revid2)])

    def test_get_parents_with_upstream_first_version(self):
        db = self.db1
        version1 = Version("0.1-1")
        up_revid = self.up_tree1.commit("one")
        db.tag_upstream_version(version1.upstream_version)
        self.assertEqual(
            db.get_parents_with_upstream("package", version1, [version1]),
            [up_revid])
        db = self.db2
        self.up_tree2.pull(self.up_tree1.branch)
        db.tag_upstream_version(version1.upstream_version)
        self.assertEqual(
            db.get_parents_with_upstream("package", version1, [version1]),
            [up_revid])

    def test_get_parents_with_upstream_second_version(self):
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        db.tag_version(version1)
        up_revid = self.up_tree1.commit("upstream one")
        db.tag_upstream_version(version1.upstream_version)
        # No upstream parent
        self.assertEqual(db.get_parents_with_upstream(
            "package", version2, [version2, version1]), [revid1])

    def test_get_parents_with_upstream_merge_from_lesser(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-0ubuntu1")
        version3 = Version("0.1-1ubuntu1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.up_tree2.pull(self.up_tree1.branch)
        self.db1.tag_upstream_version(version1.upstream_version)
        self.db2.tag_upstream_version(version2.upstream_version)
        versions = [version3, version1, version2]
        # No upstream parent
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version3, versions), [revid2, revid1])

    def test_get_parents_with_upstream_merge_from_greater(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.up_tree2.pull(self.up_tree1.branch)
        self.db1.tag_upstream_version(version1.upstream_version)
        self.db2.tag_upstream_version(version2.upstream_version)
        versions = [version3, version2, version1]
        # No upstream parent
        self.assertEqual(self.db1.get_parents_with_upstream(
            "package", version3, versions), [revid1, revid2])

    def test_get_parents_with_upstream_new_upstream_import(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-0ubuntu1")
        revid1 = self.tree1.commit("one")
        self.tree2.pull(self.tree1.branch)
        self.db1.tag_version(version1)
        self.db2.tag_version(version1)
        up_revid1 = self.up_tree1.commit("upstream one")
        up_revid2 = self.up_tree2.commit("upstream two")
        self.db1.tag_upstream_version(version1.upstream_version)
        self.db2.tag_upstream_version(version2.upstream_version)
        versions = [version2, version1]
        # Upstream parent as it is new upstream version
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version2, versions), [revid1, up_revid2])

    def test_get_parents_merge_new_upstream_from_lesser(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.2-1")
        version4 = Version("0.2-1ubuntu1")
        revid1 = self.tree1.commit("one")
        self.db1.tag_version(version1)
        revid2 = self.tree2.commit("two")
        self.db2.tag_version(version2)
        revid3 = self.tree1.commit("three")
        self.db1.tag_version(version3)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1.upstream_version)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2.upstream_version)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3.upstream_version)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version4.upstream_version)
        versions = [version4, version3, version2, version1]
        # no upstream parent as the lesser branch has already merged it
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version4, versions), [revid2, revid3])

    def test_get_parents_with_upstream_force_upstream(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        revid1 = self.tree1.commit("one")
        self.db1.tag_version(version1)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1.upstream_version)
        up_revid2 = self.up_tree2.commit("different upstream one")
        self.db2.tag_upstream_version(version2.upstream_version)
        versions = [version2, version1]
        # a previous test checked that this wouldn't give an
        # upstream parent, but we are requiring one.
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version2, versions, force_upstream_parent=True),
            [revid1, up_revid2])

    def test_get_parents_with_upstream_sync_when_diverged(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree1.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db1.tag_version(version3)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1.upstream_version)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2.upstream_version)
        versions = [version3, version2, version1]
        # This is a sync but we are diverged so we should get two
        # parents
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version3, versions), [revid2, revid3])

    def test_get_parents_with_upstream_sync_new_upstream(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.2-1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree1.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db1.tag_version(version3)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1.upstream_version)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2.upstream_version)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3.upstream_version)
        versions = [version3, version2, version1]
        # This a sync, but we are diverged, so we should get two
        # parents. There should be no upstream as the synced
        # version will already have it.
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version3, versions), [revid2, revid3])

    def test_get_parents_with_upstream_sync_new_upstream_force(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.2-1")
        revid1 = self.tree1.commit("one")
        revid2 = self.tree2.commit("two")
        revid3 = self.tree1.commit("three")
        self.db1.tag_version(version1)
        self.db2.tag_version(version2)
        self.db1.tag_version(version3)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1.upstream_version)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2.upstream_version)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3.upstream_version)
        versions = [version3, version2, version1]
        up_revid3 = self.up_tree2.commit("different upstream two")
        self.db2.tag_upstream_version(version3.upstream_version)
        versions = [version3, version2, version1]
        # test_get_parents_with_upstream_sync_new_upstream
        # checks that there is not normally an upstream parent
        # when we fake-sync, but we are forcing one here.
        #TODO: should the upstream parent be second or third?
        self.assertEqual(self.db2.get_parents_with_upstream(
            "package", version3, versions, force_upstream_parent=True),
                [revid2, up_revid3, revid3])

    def test_branch_to_pull_version_from(self):
        """Test the check for pulling from a branch.

        It should only return a branch to pull from if the version
        is present with the correct md5, and the history has not
        diverged.
        """
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        # With no versions tagged everything is None
        branch = self.db2.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_version_from(version1,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        branch = self.db1.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        # Version and md5 available, so we get the correct branch.
        self.do_commit_with_md5(self.tree1, "one", self.fake_md5_1)
        self.db1.tag_version(version1)
        branch = self.db2.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, self.db1)
        # Otherwise (different version or md5) then we get None
        branch = self.db2.branch_to_pull_version_from(version1,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_version_from(version2,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_version_from(version2,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        # And we still don't get a branch for the one that already
        # has the version
        branch = self.db1.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        # And we get the greatest branch when two lesser branches
        # have what we are looking for.
        self.tree2.pull(self.tree1.branch)
        self.db2.tag_version(version1)
        branch = self.db3.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, self.db2)
        # If the branches have diverged then we don't get a branch.
        self.tree3.commit("three")
        branch = self.db3.branch_to_pull_version_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)

    def test_branch_to_pull_upstream_from(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        # With no versions tagged everything is None
        branch = self.db2.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_2)])
        self.assertEqual(branch, None)
        branch = self.db1.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, None)
        self.do_commit_with_md5(self.up_tree1, "one", self.fake_md5_1)
        self.db1.tag_upstream_version(version1.upstream_version)
        # Version and md5 available, so we get the correct branch.
        branch = self.db2.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, self.db1)
        # Otherwise (different version or md5) then we get None
        branch = self.db2.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_2)])
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from("package",
                version2.upstream_version,
                [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from("package",
                version2.upstream_version,
                [("foo.tar.gz", None, self.fake_md5_2)])
        self.assertEqual(branch, None)
        # And we don't get a branch for the one that already has
        # the version
        branch = self.db1.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, None)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version1.upstream_version)
        # And we get the greatest branch when two lesser branches
        # have what we are looking for.
        branch = self.db3.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, self.db2)
        # If the branches have diverged then we don't get a branch.
        self.up_tree3.commit("three")
        branch = self.db3.branch_to_pull_upstream_from("package",
                version1.upstream_version, [("foo.tar.gz", None, self.fake_md5_1)])
        self.assertEqual(branch, None)

    def test_pull_from_lesser_branch_no_upstream(self):
        version = Version("0.1-1")
        self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version.upstream_version)
        up_revid = self.do_commit_with_md5(self.up_tree2, "upstream two",
                self.fake_md5_1)
        self.db2.tag_upstream_version(version.upstream_version)
        revid = self.do_commit_with_md5(self.tree1, "one", self.fake_md5_2)
        self.db1.tag_version(version)
        self.assertNotEqual(self.tree2.branch.last_revision(), revid)
        self.db2.pull_version_from_branch(self.db1, "package", version)
        self.assertEqual(self.tree2.branch.last_revision(), revid)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.revid_of_version(version), revid)
        self.assertEqual(self.db2.pristine_upstream_source.version_as_revision(
            "package", version.upstream_version), up_revid)

    def test_pull_from_lesser_branch_with_upstream(self):
        version = Version("0.1-1")
        up_revid = self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version.upstream_version)
        revid = self.do_commit_with_md5(self.tree1, "one", self.fake_md5_2)
        self.db1.tag_version(version)
        self.assertNotEqual(self.tree2.branch.last_revision(), revid)
        self.assertNotEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.db2.pull_version_from_branch(self.db1, "package", version)
        self.assertEqual(self.tree2.branch.last_revision(), revid)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.revid_of_version(version), revid)
        self.assertEqual(self.db2.pristine_upstream_source.version_as_revision(
            "package", version.upstream_version), up_revid)

    def test_pull_upstream_from_branch(self):
        version = "0.1"
        up_revid = self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version)
        self.assertNotEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.db2.pull_upstream_from_branch(self.db1, "package", version)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.pristine_upstream_source.version_as_revision("package", version),
                up_revid)

    def check_changes(self, changes, added=[], removed=[], modified=[],
                      renamed=[]):
        def check_one_type(type, expected, actual):
            def make_set(list):
                output = set()
                for item in list:
                    if item[2] == 'directory':
                        output.add(item[0] + '/')
                    else:
                        output.add(item[0])
                return output
            exp = set(expected)
            real = make_set(actual)
            missing = exp.difference(real)
            extra = real.difference(exp)
            if len(missing) > 0:
                self.fail("Some expected paths not found %s in the changes: "
                          "%s, expected %s, got %s." % (type, str(missing),
                              str(expected), str(actual)))
            if len(extra) > 0:
                self.fail("Some extra paths found %s in the changes: "
                          "%s, expected %s, got %s." % (type, str(extra),
                              str(expected), str(actual)))
        check_one_type("added", added, changes.added)
        check_one_type("removed", removed, changes.removed)
        check_one_type("modified", modified, changes.modified)
        check_one_type("renamed", renamed, changes.renamed)

    def import_a_tree(self, contents=None):
        """Import a tree from disk."""
        version = Version("0.1-1")
        name = "package"
        basedir = name + "-" + str(version.upstream_version)
        if contents is None:
            contents = [
                (basedir + '/',),
                (os.path.join(basedir, "README"), "Hi\n"),
                (os.path.join(basedir, "BUGS"), ""),
                ]
        else:
            # add basedir to the contents
            contents = [(basedir + '/' + element[0],) + element[1:] for
                element in contents]
        self.build_tree_contents(contents)
        self.db1.import_upstream(basedir, "package", version.upstream_version,
            [], [(None, None, None)])
        return version

    def test_import_upstream(self):
        version = self.import_a_tree()
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 1)
        self.assertEqual(self.db1.pristine_upstream_source.version_as_revision(
            "package", version.upstream_version), rh[0])
        rev = branch.repository.get_revision(rh[0])
        self.assertEqual(rev.message,
                "Import upstream version %s" % str(version.upstream_version))
        self.assertEqual(rev.properties.get('deb-md5'), None)

    def test_import_upstream_preserves_dot_bzrignore(self):
        self.import_a_tree([('',), ('.bzrignore', '')])
        branch = self.up_tree1.branch
        branch.lock_read()
        self.addCleanup(branch.unlock)
        tip = branch.last_revision()
        revtree = branch.repository.revision_tree(tip)
        self.assertNotEqual(None, revtree.path2id('.bzrignore'))

    def test_import_upstream_on_another(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        name = "package"
        basedir = name + "-" + str(version1.upstream_version)
        os.mkdir(basedir)
        write_to_file(os.path.join(basedir, "README"), "Hi\n")
        write_to_file(os.path.join(basedir, "BUGS"), "")
        write_to_file(os.path.join(basedir, "COPYING"), "")
        self.db1.import_upstream(basedir, "package", version1.upstream_version, [],
            [(None, None, None)])
        basedir = name + "-" + str(version2.upstream_version)
        os.mkdir(basedir)
        write_to_file(os.path.join(basedir, "README"), "Now even better\n")
        write_to_file(os.path.join(basedir, "BUGS"), "")
        write_to_file(os.path.join(basedir, "NEWS"), "")
        self.db1.import_upstream(basedir, "package", version2.upstream_version,
                [self.up_tree1.branch.last_revision()], [(None, None, None)])
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 2)
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version2.upstream_version), rh[1])
        rev = branch.repository.get_revision(rh[1])
        self.assertEqual(rev.message,
                "Import upstream version %s" % str(version2.upstream_version))
        self.assertIs(rev.properties.get('deb-md5'), None)
        rev_tree1 = branch.repository.revision_tree(rh[0])
        rev_tree2 = branch.repository.revision_tree(rh[1])
        changes = rev_tree2.changes_from(rev_tree1)
        self.check_changes(changes, added=["NEWS"], removed=["COPYING"],
                modified=["README"])

    def test_import_upstream_with_tarball(self):
        self.requireFeature(PristineTarFeature)
        version = Version("0.1-1")
        name = "package"
        basedir = name + "-" + str(version.upstream_version)
        os.mkdir(basedir)
        write_to_file(os.path.join(basedir, "README"), "Hi\n")
        write_to_file(os.path.join(basedir, "BUGS"), "")
        tar_path = "package_0.1.orig.tar.gz"
        tf = tarfile.open(tar_path, 'w:gz')
        try:
            tf.add(basedir)
        finally:
            tf.close()
        self.db1.import_upstream(basedir, "package", version.upstream_version, [],
                upstream_tarballs=[(os.path.abspath(tar_path), None, self.fake_md5_1)])
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 1)
        self.assertEqual(self.db1.pristine_upstream_source.version_as_revision(
            "package", version.upstream_version), rh[0])
        rev = branch.repository.get_revision(rh[0])
        self.assertEqual(rev.message,
                "Import upstream version %s" % str(version.upstream_version))
        self.assertEqual(rev.properties['deb-md5'], self.fake_md5_1)
        self.assertTrue('deb-pristine-delta' in rev.properties)

    def test_import_upstream_with_bzip2_tarball(self):
        self.requireFeature(PristineTarFeature)
        version = Version("0.1-1")
        name = "package"
        basedir = name + "-" + str(version.upstream_version)
        os.mkdir(basedir)
        write_to_file(os.path.join(basedir, "README"), "Hi\n")
        write_to_file(os.path.join(basedir, "BUGS"), "")
        tar_path = "package_0.1.orig.tar.bz2"
        tf = tarfile.open(tar_path, 'w:bz2')
        try:
            tf.add(basedir)
        finally:
            tf.close()
        self.db1.import_upstream(basedir, "package", version.upstream_version,
            [], upstream_tarballs=[(os.path.abspath(tar_path), None, self.fake_md5_1)])
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 1)
        self.assertEqual(self.db1.pristine_upstream_source.version_as_revision(
            "package", version.upstream_version), rh[0])
        rev = branch.repository.get_revision(rh[0])
        self.assertEqual(rev.message,
                "Import upstream version %s" % str(version.upstream_version))
        self.assertEqual(rev.properties['deb-md5'], self.fake_md5_1)
        self.assertTrue('deb-pristine-delta-bz2' in rev.properties)

    def test_import_package_init_from_other(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db1.pristine_upstream_tree = None
        builder.new_version(version2)
        builder.build()
        self.db2.import_package(builder.dsc_name())
        self.assertEqual(len(self.up_tree2.branch.revision_history()), 2)
        self.assertEqual(len(self.tree2.branch.revision_history()), 3)

    def test_import_package_init_upstream_from_other(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db2.import_package(builder.dsc_name())
        self.db2.pristine_upstream_tree = None
        builder.new_version(version2)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.assertEqual(len(self.up_tree1.branch.revision_history()), 1)
        self.assertEqual(len(self.tree1.branch.revision_history()), 3)

    def import_package_single(self):
        version1 = Version("0.1-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_upstream_file("README", "foo")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.assertEqual(len(self.up_tree1.branch.revision_history()), 1)
        self.assertEqual(len(self.tree1.branch.revision_history()), 2)

    def test_import_package_double(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_upstream_file("README", "foo")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("NEWS")
        builder.add_debian_file("COPYING", "Don't do it\n")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        change_text = ("  [ Other Maint ]\n"
                "  * Foo, thanks Bar \n"
                "  * Bar, thanks Foo <foo@foo.org>\n\n")
        builder.new_version(version2, change_text=change_text)
        builder.add_upstream_file("README", "bar")
        builder.add_upstream_file("COPYING", "Please do\n")
        builder.add_upstream_file("src.c")
        builder.remove_upstream_file("NEWS")
        builder.remove_debian_file("COPYING")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh = self.tree1.branch.revision_history()
        up_rh = self.up_tree1.branch.revision_history()
        self.assertEqual(len(up_rh), 2)
        self.assertEqual(len(rh), 3)
        self.assertEqual(rh[0], up_rh[0])
        self.assertNotEqual(rh[1], up_rh[1])
        # Check the parents are correct.
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh[1])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh[2])
        up_rev_tree1 = self.up_tree1.branch.repository.revision_tree(up_rh[0])
        up_rev_tree2 = self.up_tree1.branch.repository.revision_tree(up_rh[1])
        self.assertEqual(up_rev_tree1.get_parent_ids(), [])
        self.assertEqual(up_rev_tree2.get_parent_ids(), [up_rh[0]])
        self.assertEqual(rev_tree1.get_parent_ids(), [up_rh[0]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh[1], up_rh[1]])
        # Check that the file ids are correct.
        self.check_changes(up_rev_tree2.changes_from(up_rev_tree1),
                added=["COPYING", "src.c"], removed=["NEWS"],
                modified=["README"])
        self.check_changes(rev_tree1.changes_from(up_rev_tree1),
                added=["debian/", "debian/changelog", "COPYING",
                "debian/control"])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["debian/changelog", "COPYING", "README"],
                added=["src.c"], removed=["NEWS"])
        self.check_changes(rev_tree2.changes_from(up_rev_tree2),
                added=["debian/", "debian/changelog", "debian/control"])
        self.check_changes(up_rev_tree2.changes_from(rev_tree1),
                added=["src.c"],
                removed=["NEWS", "debian/", "debian/changelog",
                "debian/control"],
                modified=["README", "COPYING"])
        revid = self.tree1.last_revision()
        imported_rev = self.tree1.branch.repository.get_revision(revid)
        props = imported_rev.properties
        self.assertEqual(props["authors"], "Maint <maint@maint.org>\n"
                "Other Maint")
        self.assertEqual(props["deb-thanks"], "Bar\nFoo <foo@foo.org>")

    def test_import_two_roots(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-0ubuntu1")
        version2 = Version("0.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_upstream_file("README", "foo")
        builder.add_default_control()
        builder.build()
        self.db2.import_package(builder.dsc_name())
        builder = SourcePackageBuilder("package", version2)
        builder.add_upstream_file("README", "bar")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        rh2 = self.tree2.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        up_rh2 = self.up_tree2.branch.revision_history()
        self.assertEqual(len(rh1), 2)
        self.assertEqual(len(rh2), 2)
        self.assertEqual(len(up_rh1), 1)
        self.assertEqual(len(up_rh2), 1)
        self.assertNotEqual(rh1, rh2)
        self.assertNotEqual(rh1[0], rh2[0])
        self.assertNotEqual(rh1[1], rh2[1])
        self.assertEqual(rh1[0], up_rh1[0])
        self.assertEqual(rh2[0], up_rh2[0])
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[1])
        rev_tree2 = self.tree2.branch.repository.revision_tree(rh2[1])
        up_rev_tree1 = self.up_tree1.branch.repository.revision_tree(rh1[0])
        up_rev_tree2 = self.up_tree2.branch.repository.revision_tree(rh2[0])
        self.check_changes(rev_tree1.changes_from(up_rev_tree1),
                added=["debian/", "debian/changelog", "debian/control"])
        self.check_changes(rev_tree2.changes_from(up_rev_tree2),
                added=["debian/", "debian/changelog", "debian/control"])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["README", "debian/changelog"])
        self.check_changes(up_rev_tree2.changes_from(up_rev_tree1),
                modified=["README"])

    def test_sync_to_other_branch(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        version3 = Version("0.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_upstream_file("README", "foo")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        builder.new_version(version2)
        builder.add_upstream_file("README", "bar")
        builder.add_default_control()
        builder.build()
        self.db2.import_package(builder.dsc_name())
        builder = SourcePackageBuilder("package", version1)
        builder.new_version(version3)
        builder.add_upstream_file("README", "baz")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        rh2 = self.tree2.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        up_rh2 = self.up_tree2.branch.revision_history()
        self.assertEqual(len(rh1), 3)
        self.assertEqual(len(rh2), 4)
        self.assertEqual(len(up_rh1), 2)
        self.assertEqual(len(up_rh2), 2)
        self.assertEqual(rh1[0], up_rh1[0])
        self.assertEqual(rh2[0], up_rh2[0])
        self.assertEqual(rh1[0], rh2[0])
        self.assertEqual(rh1[1], rh2[1])
        self.assertNotEqual(rh1[2], rh2[2])
        self.assertEqual(up_rh1[1], up_rh2[1])
        rev_tree1 = self.tree2.branch.repository.revision_tree(rh2[2])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[2])
        rev_tree3 = self.tree2.branch.repository.revision_tree(rh2[3])
        self.assertEqual(rev_tree1.get_parent_ids(), [rh2[1]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[1], up_rh1[1]])
        self.assertEqual(rev_tree3.get_parent_ids(), [rh2[2], rh1[2]])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["README", "debian/changelog"])
        self.check_changes(rev_tree3.changes_from(rev_tree2))
        self.check_changes(rev_tree3.changes_from(rev_tree1),
                modified=["README", "debian/changelog"])

    def test_pull_from_other(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        version3 = Version("0.3-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        builder.new_version(version2)
        builder.build()
        self.db2.import_package(builder.dsc_name())
        builder.new_version(version3)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        self.assertEqual(3, len(self.tree1.branch.revision_history()))
        self.assertEqual(2, len(self.up_tree1.branch.revision_history()))
        self.assertEqual(3, len(self.tree2.branch.revision_history()))
        self.assertEqual(2, len(self.up_tree2.branch.revision_history()))
        self.assertEqual(self.tree1.last_revision(),
                self.tree2.last_revision())
        self.assertEqual(self.up_tree1.last_revision(),
                self.up_tree2.last_revision())

    def test_is_native_version(self):
        version1 = Version("0.1-0ubuntu1")
        version2 = Version("0.2-1")
        self.tree1.commit("one")
        self.db1.tag_version(version1)
        self.tree1.commit("two", revprops={'deb-native': "True"})
        self.db1.tag_version(version2)
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertFalse(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))

    def test_import_native(self):
        version = Version("1.0")
        builder = SourcePackageBuilder("package", version, native=True)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 1)
        self.assertEqual(len(up_rh1), 0)
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertTrue(self.db1.is_version_native(version))
        revtree = self.tree1.branch.repository.revision_tree(rh1[0])
        self.assertTrue(self.db1._is_tree_native(revtree))

    def test_import_native_two(self):
        version1 = Version("1.0")
        version2 = Version("1.1")
        builder = SourcePackageBuilder("package", version1, native=True)
        builder.add_debian_file("COPYING", "don't do it\n")
        builder.add_debian_file("README")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.new_version(version2)
        builder.remove_debian_file("README")
        builder.add_debian_file("COPYING", "do it\n")
        builder.add_debian_file("NEWS")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 2)
        self.assertEqual(len(up_rh1), 0)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[0])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[1])
        self.assertEqual(rev_tree1.get_parent_ids(), [])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[0]])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                added=["NEWS"], removed=["README"],
                modified=["debian/changelog", "COPYING"])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[0])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[1])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertTrue(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))

    def test_import_native_two_unrelated(self):
        version1 = Version("1.0")
        version2 = Version("1.1")
        builder = SourcePackageBuilder("package", version1, native=True)
        builder.add_default_control()
        builder.add_upstream_file("README", "foo")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder = SourcePackageBuilder("package", version2, native=True)
        builder.add_default_control()
        builder.add_upstream_file("README", "bar")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 2)
        self.assertEqual(len(up_rh1), 0)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[0])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[1])
        self.assertEqual(rev_tree1.get_parent_ids(), [])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[0]])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["README", "debian/changelog"])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[0])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[1])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertTrue(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))

    def test_import_non_native_to_native(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.0-2")
        builder = SourcePackageBuilder("package", version1)
        builder.add_upstream_file("COPYING", "don't do it\n")
        builder.add_upstream_file("BUGS")
        builder.add_debian_file("README", "\n")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = True
        builder.new_version(version2)
        builder.remove_upstream_file("BUGS")
        builder.add_upstream_file("COPYING", "do it\n")
        builder.add_upstream_file("NEWS")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 3)
        self.assertEqual(len(up_rh1), 1)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[1])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[2])
        self.assertEqual(rev_tree1.get_parent_ids(), [rh1[0]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[1]])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                added=["NEWS", ".bzr-builddeb/",
                    ".bzr-builddeb/default.conf"],
                removed=["BUGS"], modified=["debian/changelog", "COPYING"])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[1])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[2])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertFalse(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))

    def test_import_native_to_non_native(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0")
        version2 = Version("1.1-1")
        builder = SourcePackageBuilder("package", version1, native=True)
        builder.add_upstream_file("COPYING", "don't do it\n")
        builder.add_upstream_file("BUGS")
        builder.add_debian_file("README", "\n")
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = False
        builder.new_version(version2)
        builder.remove_upstream_file("BUGS")
        builder.add_upstream_file("COPYING", "do it\n")
        builder.add_upstream_file("NEWS")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 2)
        self.assertEqual(len(up_rh1), 2)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[0])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[1])
        up_rev_tree1 = \
                self.up_tree1.branch.repository.revision_tree(up_rh1[1])
        self.assertEqual(rev_tree1.get_parent_ids(), [])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[0], up_rh1[1]])
        self.assertEqual(up_rev_tree1.get_parent_ids(), [rh1[0]])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                added=["NEWS"],
                removed=["BUGS", ".bzr-builddeb/",
                    ".bzr-builddeb/default.conf"],
                modified=["debian/changelog", "COPYING"])
        self.check_changes(up_rev_tree1.changes_from(rev_tree1),
                added=["NEWS"],
                removed=["debian/", "debian/changelog", "debian/control",
                        "BUGS", "README", ".bzr-builddeb/",
                        ".bzr-builddeb/default.conf"],
                modified=["COPYING"])
        self.check_changes(rev_tree2.changes_from(up_rev_tree1),
                added=["debian/", "debian/changelog", "debian/control",
                "README"])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[0])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[1])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertTrue(self.db1.is_version_native(version1))
        self.assertFalse(self.db1.is_version_native(version2))

    def test_import_to_native_and_back_same_upstream(self):
        """Non-native to native and back all in the same upstream version.

        As the native version was on the same upstream as a non-native
        version we assume that it was accidental, and so don't include
        the native revision in the upstream branch's history.
        """
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.0-2")
        version3 = Version("1.0-3")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = True
        builder.new_version(version2)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = False
        builder.new_version(version3)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 4)
        self.assertEqual(len(up_rh1), 1)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[1])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[2])
        rev_tree3 = self.tree1.branch.repository.revision_tree(rh1[3])
        self.assertEqual(rev_tree1.get_parent_ids(), [up_rh1[0]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[1]])
        self.assertEqual(rev_tree3.get_parent_ids(), [rh1[2]])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[1])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[2])
        self.assertEqual(self.db1.revid_of_version(version3), rh1[3])
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version1.upstream_version),
            up_rh1[0])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertFalse(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))
        self.assertFalse(self.db1.is_version_native(version3))

    def test_import_to_native_and_back_new_upstream(self):
        """Non-native to native and back with a new upstream version.
           
        As the native version was on the same upstream as a non-native
        version we assume that it was accidental, and so don't include
        the native revision in the upstream branch's history.

        As we get a new upstream we want to link that to the previous
        upstream.
        """
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.0-2")
        version3 = Version("1.1-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = True
        builder.new_version(version2)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = False
        builder.new_version(version3)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 4)
        self.assertEqual(len(up_rh1), 2)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[1])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[2])
        rev_tree3 = self.tree1.branch.repository.revision_tree(rh1[3])
        up_rev_tree1 = \
                self.up_tree1.branch.repository.revision_tree(up_rh1[0])
        up_rev_tree2 = \
                self.up_tree1.branch.repository.revision_tree(up_rh1[1])
        self.assertEqual(rev_tree1.get_parent_ids(), [up_rh1[0]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[1]])
        self.assertEqual(rev_tree3.get_parent_ids(), [rh1[2], up_rh1[1]])
        self.assertEqual(up_rev_tree2.get_parent_ids(), [up_rh1[0]])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[1])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[2])
        self.assertEqual(self.db1.revid_of_version(version3), rh1[3])
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version1.upstream_version),
            up_rh1[0])
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version3.upstream_version),
            up_rh1[1])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertFalse(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))
        self.assertFalse(self.db1.is_version_native(version3))

    def test_import_to_native_and_back_all_different_upstreams(self):
        """Non-native to native and back with all different upstreams.
           
        In this case we want to assume the package was "intended" to
        be native, and so we include the native version in the upstream
        history (i.e. the upstream part of the last version has
        the second version's packaging branch revision as the second
        parent).
        """
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1")
        version3 = Version("1.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = True
        builder.new_version(version2)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        builder.native = False
        builder.new_version(version3)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        self.assertEqual(len(rh1), 4)
        self.assertEqual(len(up_rh1), 2)
        rev_tree1 = self.tree1.branch.repository.revision_tree(rh1[1])
        rev_tree2 = self.tree1.branch.repository.revision_tree(rh1[2])
        rev_tree3 = self.tree1.branch.repository.revision_tree(rh1[3])
        up_rev_tree1 = \
                self.up_tree1.branch.repository.revision_tree(up_rh1[0])
        up_rev_tree2 = \
                self.up_tree1.branch.repository.revision_tree(up_rh1[1])
        self.assertEqual(rev_tree1.get_parent_ids(), [up_rh1[0]])
        self.assertEqual(rev_tree2.get_parent_ids(), [rh1[1]])
        self.assertEqual(rev_tree3.get_parent_ids(), [rh1[2], up_rh1[1]])
        self.assertEqual(up_rev_tree2.get_parent_ids(), [up_rh1[0], rh1[2]])
        self.assertEqual(self.db1.revid_of_version(version1), rh1[1])
        self.assertEqual(self.db1.revid_of_version(version2), rh1[2])
        self.assertEqual(self.db1.revid_of_version(version3), rh1[3])
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version1.upstream_version),
            up_rh1[0])
        self.assertEqual(
            self.db1.pristine_upstream_source.version_as_revision("package", version3.upstream_version),
            up_rh1[1])
        self.tree1.lock_read()
        self.addCleanup(self.tree1.unlock)
        self.assertFalse(self.db1.is_version_native(version1))
        self.assertTrue(self.db1.is_version_native(version2))
        self.assertFalse(self.db1.is_version_native(version3))
        # TODO: test that file-ids added in the native version
        # are used in the second non-native upstream

    def test_merge_upstream_branches(self):
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1-1")
        version3 = Version("1.2-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        builder.new_version(version2)
        builder.build()
        self.db2.import_package(builder.dsc_name())
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.new_version(version3)
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.db2.import_package(builder.dsc_name())
        rh1 = self.tree1.branch.revision_history()
        up_rh1 = self.up_tree1.branch.revision_history()
        rh2 = self.tree2.branch.revision_history()
        up_rh2 = self.up_tree2.branch.revision_history()
        self.assertEqual(3, len(rh1))
        self.assertEqual(2, len(up_rh1))
        self.assertEqual(4, len(rh2))
        self.assertEqual(3, len(up_rh2))
        revtree = self.tree2.branch.repository.revision_tree(rh2[-1])
        self.assertEqual(3, len(revtree.get_parent_ids()))
        self.assertEqual(up_rh2[-1], revtree.get_parent_ids()[1])
        self.assertEqual(rh1[-1], revtree.get_parent_ids()[2])
        up_revtree = self.tree2.branch.repository.revision_tree(up_rh2[-1])
        self.assertEqual(2, len(up_revtree.get_parent_ids()))
        self.assertEqual(up_rh1[-1], up_revtree.get_parent_ids()[1])
        self.assertEqual(up_rh2[-1],
                self.tree2.branch.tags.lookup_tag("upstream-1.2"))

    def test_merge_upstream_initial(self):
        """Verify we can go from normal branches to merge-upstream."""
        tree = self.make_branch_and_tree('work')
        self.build_tree(['work/a'])
        tree.add(['a'])
        orig_upstream_rev = tree.commit("one")
        tree.branch.tags.set_tag("upstream-0.1", orig_upstream_rev)
        self.build_tree(['work/debian/'])
        cl = self.make_changelog(version="0.1-1")
        self.write_changelog(cl, 'work/debian/changelog')
        tree.add(['debian/', 'debian/changelog'])
        orig_debian_rev = tree.commit("two")
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tarball_filename = "package-0.2.tar.gz"
        tf = tarfile.open(tarball_filename, 'w:gz')
        try:
            f = open("a", "wb")
            try:
                f.write("aaa")
            finally:
                f.close()
            tf.add("a")
        finally:
            tf.close()
        conflicts = db.merge_upstream([(tarball_filename, None)], "foo", "0.2", "0.1")
        self.assertEqual(0,  conflicts)

    def test_merge_upstream_initial_with_branch(self):
        """Verify we can go from normal branches to merge-upstream."""
        tree = self.make_branch_and_tree('work')
        self.build_tree(['work/a'])
        tree.add(['a'])
        orig_upstream_rev = tree.commit("one")
        upstream_tree = self.make_branch_and_tree('upstream')
        upstream_tree.pull(tree.branch)
        tree.branch.tags.set_tag("upstream-0.1", orig_upstream_rev)
        self.build_tree(['work/debian/'])
        cl = self.make_changelog(version="0.1-1")
        self.write_changelog(cl, 'work/debian/changelog')
        tree.add(['debian/', 'debian/changelog'])
        orig_debian_rev = tree.commit("two")
        self.build_tree(['upstream/a'])
        upstream_rev = upstream_tree.commit("three")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        upstream_tree.lock_read()
        self.addCleanup(upstream_tree.unlock)
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tarball_filename = "package-0.2.tar.gz"
        tf = tarfile.open(tarball_filename, 'w:gz')
        try:
            f = open("a", "wb")
            try:
                f.write("aaa")
            finally:
                f.close()
            tf.add("a")
        finally:
            tf.close()
        conflicts = db.merge_upstream([(tarball_filename, None)], "foo", "0.2", "0.1",
            upstream_branch=upstream_tree.branch,
            upstream_revision=upstream_rev)
        self.assertEqual(0,  conflicts)

    def test_merge_upstream_initial_with_removed_debian(self):
        """Verify we can go from normal branches to merge-upstream."""
        tree = self.make_branch_and_tree('work')
        self.build_tree(['work/a', 'work/debian/'])
        cl = self.make_changelog(version="0.1-1")
        self.write_changelog(cl, 'work/debian/changelog')
        tree.add(['a', 'debian/', 'debian/changelog'])
        orig_upstream_rev = tree.commit("one")
        upstream_tree = self.make_branch_and_tree('upstream')
        upstream_tree.pull(tree.branch)
        tree.branch.tags.set_tag("upstream-0.1", orig_upstream_rev)
        cl.add_change('  * something else')
        self.write_changelog(cl, 'work/debian/changelog')
        orig_debian_rev = tree.commit("two")
        self.build_tree(['upstream/a'])
        shutil.rmtree('upstream/debian')
        upstream_rev = upstream_tree.commit("three")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        upstream_tree.lock_read()
        self.addCleanup(upstream_tree.unlock)
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tarball_filename = "package-0.2.tar.gz"
        tf = tarfile.open(tarball_filename, 'w:gz')
        try:
            f = open("a", "wb")
            try:
                f.write("aaa")
            finally:
                f.close()
            tf.add("a")
        finally:
            tf.close()
        conflicts = db.merge_upstream([(tarball_filename, None)], "foo", "0.2", "0.1",
            upstream_branch=upstream_tree.branch,
            upstream_revision=upstream_rev)
        # ./debian conflicts.
        self.assertEqual(3,  conflicts)

    def test_merge_upstream_with_unrelated_branch(self):
        """Check that we can merge-upstream with an unrelated branch.

        We should do this by changing all the file ids to be the same
        as in the upstream branch, which gives a discontinuity, but
        makes for a better experience in the future.
        """
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1-1")
        builder = SourcePackageBuilder("package", version1)
        builder.add_default_control()
        builder.add_upstream_file("a", "Original a")
        builder.build()
        tree = self.make_branch_and_tree(".")
        packaging_upstream_tree = self.make_branch_and_tree(
            "packaging-upstream")
        db = DistributionBranch(tree.branch, packaging_upstream_tree.branch,
            tree=tree, pristine_upstream_tree=packaging_upstream_tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        db.import_package(builder.dsc_name())
        builder.new_version(version2)
        builder.add_upstream_file("a", "New a")
        builder.build()
        upstream_tree = self.make_branch_and_tree("upstream")
        self.build_tree(['upstream/a'])
        upstream_tree.add(['a'], ['a-id'])
        upstream_tree.commit("one")
        upstream_rev = upstream_tree.branch.last_revision()
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        db.merge_upstream([(builder.tar_name(), None)], "package", str(version2),
            version1.upstream_version,
            upstream_branch=upstream_tree.branch,
            upstream_revision=upstream_rev)
        rh1 = tree.branch.revision_history()
        self.assertEqual(2, len(rh1))
        packaging_upstream_tip = tree.get_parent_ids()[1]
        # We added the extra parent for the upstream branch
        revtree = tree.branch.repository.revision_tree(packaging_upstream_tip)
        self.assertEqual(2, len(revtree.get_parent_ids()))
        self.assertEqual(upstream_rev, revtree.get_parent_ids()[1])
        # And the file has the new id in our tree
        self.assertEqual("a-id", tree.path2id("a"))

    def test_merge_upstream_with_dash_in_version_number(self):
        tree = self.make_branch_and_tree('work')
        self.build_tree(['work/a'])
        tree.add(['a'])
        orig_upstream_rev = tree.commit("one")
        tree.branch.tags.set_tag("upstream-0.1", orig_upstream_rev)
        self.build_tree(['work/debian/'])
        cl = self.make_changelog(version="0.1-1")
        self.write_changelog(cl, 'work/debian/changelog')
        tree.add(['debian/', 'debian/changelog'])
        orig_debian_rev = tree.commit("two")
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tarball_filename = "package-0.2.tar.gz"
        tf = tarfile.open(tarball_filename, 'w:gz')
        try:
            f = open("a", "wb")
            try:
                f.write("aaa")
            finally:
                f.close()
            tf.add("a")
        finally:
            tf.close()
        conflicts = db.merge_upstream([(tarball_filename, None)], "package", "0.2-1",
            "0.1")
        # Check that we tagged wiht the dash version
        self.assertTrue(tree.branch.tags.has_tag('upstream-0.2-1'))

    def test_merge_upstream_rename_and_replace(self):
        """Test renaming a file upstream and replacing it.

        We want to take the rename in to our tree, but have to be
        careful not to assign the file id to the new file at the same
        path as well, as that will lead to problems.
        """
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1-1")
        upstream_tree = self.make_branch_and_tree("upstream")
        upstream_tree.lock_write()
        self.addCleanup(upstream_tree.unlock)
        self.build_tree(['upstream/a'])
        upstream_tree.add(['a'], ['a-id'])
        upstream_rev1 = upstream_tree.commit("one")
        tree = upstream_tree.bzrdir.sprout('packaging').open_workingtree()
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("add packaging")
        tree.branch.tags.set_tag("upstream-%s" % version1.upstream_version,
                upstream_rev1)
        builder = SourcePackageBuilder("package", version2)
        builder.add_default_control()
        builder.add_upstream_file("a", "New a")
        builder.add_upstream_file("b", "Renamed a")
        builder.build()
        upstream_tree.rename_one('a', 'b')
        # We don't add the new file upstream, as the new file id would
        # be picked up from there.
        upstream_rev2 = upstream_tree.commit("two")
        db.merge_upstream([(builder.tar_name(), None)], "package",
            version2.upstream_version,
            version1.upstream_version,
            upstream_branch=upstream_tree.branch,
            upstream_revision=upstream_rev2)
        self.assertEqual("a-id", tree.path2id("b"))

    def test_merge_upstream_rename_on_top(self):
        """Test renaming a file upstream, replacing an existing file."""
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1-1")
        upstream_tree = self.make_branch_and_tree("upstream")
        upstream_tree.lock_write()
        self.addCleanup(upstream_tree.unlock)
        self.build_tree(['upstream/a', 'upstream/b'])
        upstream_tree.add(['a', 'b'], ['a-id', 'b-id'])
        upstream_rev1 = upstream_tree.commit("one")
        tree = upstream_tree.bzrdir.sprout('packaging').open_workingtree()
        db = DistributionBranch(tree.branch, tree.branch, tree=tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("add packaging")
        tree.branch.tags.set_tag("upstream-%s" % version1.upstream_version,
                upstream_rev1)
        builder = SourcePackageBuilder("package", version2)
        builder.add_default_control()
        builder.add_upstream_file("b", "Renamed a")
        builder.build()
        upstream_tree.unversion(['b-id'])
        os.unlink('upstream/b')
        upstream_tree.rename_one('a', 'b')
        # We don't add the new file upstream, as the new file id would
        # be picked up from there.
        upstream_rev2 = upstream_tree.commit("two")
        db.merge_upstream([(builder.tar_name(), None)], "package",
            version2.upstream_version,
            version1.upstream_version,
            upstream_branch=upstream_tree.branch,
            upstream_revision=upstream_rev2)
        self.assertEqual("a-id", tree.path2id("b"))

    def test_merge_upstream_rename_in_packaging_branch(self):
        """Test renaming a file in the packaging branch."""
        self.requireFeature(PristineTarFeature)
        version1 = Version("1.0-1")
        version2 = Version("1.1-1")
        packaging_tree = self.make_branch_and_tree("packaging")
        packaging_tree.lock_write()
        self.addCleanup(packaging_tree.unlock)
        self.build_tree(['packaging/a'])
        packaging_tree.add(['a'], ['a-id'])
        upstream_rev1 = packaging_tree.commit("one")
        db = DistributionBranch(packaging_tree.branch, packaging_tree.branch,
            tree=packaging_tree)
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        packaging_tree.rename_one('a', 'b')
        self.build_tree(['packaging/a'])
        packaging_tree.add(['a'], ['other-a-id'])
        packaging_tree.commit("add packaging")
        packaging_tree.branch.tags.set_tag("upstream-%s" % version1.upstream_version,
                upstream_rev1)
        builder = SourcePackageBuilder("package", version2)
        builder.add_default_control()
        builder.add_upstream_file("a", "New a")
        builder.add_upstream_file("b", "Renamed a")
        builder.build()
        db.merge_upstream([(builder.tar_name(), None)], "packaging",
            version2.upstream_version, version1.upstream_version)
        self.assertEqual("a-id", packaging_tree.path2id("b"))
        self.assertEqual("other-a-id", packaging_tree.path2id("a"))

    def test_import_symlink(self):
        version = Version("1.0-1")
        self.requireFeature(PristineTarFeature)
        self.requireFeature(tests.SymlinkFeature)
        builder = SourcePackageBuilder("package", version)
        builder.add_default_control()
        builder.add_upstream_symlink("a", "b")
        builder.build()
        self.db1.import_package(builder.dsc_name())


class OneZeroSourceExtractorTests(tests.TestCaseInTempDir):

    def test_extract_format1(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(OneZeroSourceExtractor, SOURCE_EXTRACTORS[dsc['Format']])
        extractor = OneZeroSourceExtractor(builder.dsc_name(), dsc)
        try:
            extractor.extract()
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))
        finally:
            extractor.cleanup()

    def test_extract_format1_native(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, native=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(OneZeroSourceExtractor, SOURCE_EXTRACTORS[dsc['Format']])
        extractor = OneZeroSourceExtractor(builder.dsc_name(), dsc)
        try:
            extractor.extract()
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertEqual(None, orig_dir)
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
        finally:
            extractor.cleanup()

    def test_extract_format3_native(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, native=True,
                version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(ThreeDotZeroNativeSourceExtractor,
                SOURCE_EXTRACTORS[dsc['Format']])
        extractor = ThreeDotZeroNativeSourceExtractor(builder.dsc_name(),
                dsc)
        try:
            extractor.extract()
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertEqual(None, orig_dir)
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
        finally:
            extractor.cleanup()

    def test_extract_format3_quilt(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(ThreeDotZeroQuiltSourceExtractor,
                SOURCE_EXTRACTORS[dsc['Format']])
        extractor = ThreeDotZeroQuiltSourceExtractor(builder.dsc_name(), dsc)
        try:
            extractor.extract()
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))
        finally:
            extractor.cleanup()

    def test_extract_format3_quilt_bz2(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build(tar_format='bz2')
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(ThreeDotZeroQuiltSourceExtractor,
                SOURCE_EXTRACTORS[dsc['Format']])
        extractor = ThreeDotZeroQuiltSourceExtractor(builder.dsc_name(), dsc)
        try:
            extractor.extract()
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))
        finally:
            extractor.cleanup()

    def test_extract_format3_quilt_multiple_upstream_tarballs(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, version3=True,
                multiple_upstream_tarballs=("foo", "bar"))
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("foo/wibble")
        builder.add_upstream_file("bar/xyzzy")
        builder.add_default_control()
        builder.build(tar_format='bz2')
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(ThreeDotZeroQuiltSourceExtractor,
                SOURCE_EXTRACTORS[dsc['Format']])
        extractor = ThreeDotZeroQuiltSourceExtractor(builder.dsc_name(), dsc)
        self.addCleanup(extractor.cleanup)
        self.assertEquals([], extractor.upstream_tarballs)
