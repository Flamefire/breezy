# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the 'checkout' CLI command."""

import os

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    errors,
    workingtree,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )
from bzrlib.tests.features import (
    HardlinkFeature,
    )


class TestCheckout(TestCaseWithTransport):

    def setUp(self):
        super(TestCheckout, self).setUp()
        tree = bzrdir.BzrDir.create_standalone_workingtree('branch')
        tree.commit('1', rev_id='1', allow_pointless=True)
        self.build_tree(['branch/added_in_2'])
        tree.add('added_in_2')
        tree.commit('2', rev_id='2')

    def test_checkout_makes_bound_branch(self):
        self.run_bzr('checkout branch checkout')
        # if we have a checkout, the branch base should be 'branch'
        source = bzrdir.BzrDir.open('branch')
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(source.open_branch().bzrdir.root_transport.base,
                         result.open_branch().get_bound_location())

    def test_checkout_light_makes_checkout(self):
        self.run_bzr('checkout --lightweight branch checkout')
        # if we have a checkout, the branch base should be 'branch'
        source = bzrdir.BzrDir.open('branch')
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(source.open_branch().bzrdir.root_transport.base,
                         result.open_branch().bzrdir.root_transport.base)

    def test_checkout_dash_r(self):
        out, err = self.run_bzr(['checkout', '-r', '-2', 'branch', 'checkout'])
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(['1'], result.open_workingtree().get_parent_ids())
        self.assertPathDoesNotExist('checkout/added_in_2')

    def test_checkout_light_dash_r(self):
        out, err = self.run_bzr(['checkout','--lightweight', '-r', '-2',
            'branch', 'checkout'])
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(['1'], result.open_workingtree().get_parent_ids())
        self.assertPathDoesNotExist('checkout/added_in_2')

    def test_checkout_reconstitutes_working_trees(self):
        # doing a 'bzr checkout' in the directory of a branch with no tree
        # or a 'bzr checkout path' with path the name of a directory with
        # a branch with no tree will reconsistute the tree.
        os.mkdir('treeless-branch')
        branch = bzrdir.BzrDir.create_branch_convenience(
            'treeless-branch',
            force_new_tree=False,
            format=bzrdir.BzrDirMetaFormat1())
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.bzrdir.open_workingtree)
        out, err = self.run_bzr('checkout treeless-branch')
        # we should have a tree now
        branch.bzrdir.open_workingtree()
        # with no diff
        out, err = self.run_bzr('diff treeless-branch')

        # now test with no parameters
        branch = bzrdir.BzrDir.create_branch_convenience(
            '.',
            force_new_tree=False,
            format=bzrdir.BzrDirMetaFormat1())
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.bzrdir.open_workingtree)
        out, err = self.run_bzr('checkout')
        # we should have a tree now
        branch.bzrdir.open_workingtree()
        # with no diff
        out, err = self.run_bzr('diff')

    def _test_checkout_existing_dir(self, lightweight):
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', 'content1'),
                                  ('source/file2', 'content2'),])
        source.add(['file1', 'file2'])
        source.commit('added files')
        self.build_tree_contents([('target/', ''),
                                  ('target/file1', 'content1'),
                                  ('target/file2', 'content3'),])
        cmd = ['checkout', 'source', 'target']
        if lightweight:
            cmd.append('--lightweight')
        self.run_bzr('checkout source target')
        # files with unique content should be moved
        self.assertPathExists('target/file2.moved')
        # files with content matching tree should not be moved
        self.assertPathDoesNotExist('target/file1.moved')

    def test_checkout_existing_dir_heavy(self):
        self._test_checkout_existing_dir(False)

    def test_checkout_existing_dir_lightweight(self):
        self._test_checkout_existing_dir(True)

    def test_checkout_in_branch_with_r(self):
        branch = _mod_branch.Branch.open('branch')
        branch.bzrdir.destroy_workingtree()
        os.chdir('branch')
        self.run_bzr('checkout -r 1')
        tree = workingtree.WorkingTree.open('.')
        self.assertEqual('1', tree.last_revision())
        branch.bzrdir.destroy_workingtree()
        self.run_bzr('checkout -r 0')
        self.assertEqual('null:', tree.last_revision())

    def test_checkout_files_from(self):
        branch = _mod_branch.Branch.open('branch')
        self.run_bzr(['checkout', 'branch', 'branch2', '--files-from',
                      'branch'])

    def test_checkout_hardlink(self):
        self.requireFeature(HardlinkFeature)
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1'])
        source.add('file1')
        source.commit('added file')
        out, err = self.run_bzr('checkout source target --hardlink')
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)

    def test_checkout_hardlink_files_from(self):
        self.requireFeature(HardlinkFeature)
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1'])
        source.add('file1')
        source.commit('added file')
        source.bzrdir.sprout('second')
        out, err = self.run_bzr('checkout source target --hardlink'
                                ' --files-from second')
        second_stat = os.stat('second/file1')
        target_stat = os.stat('target/file1')
        self.assertEqual(second_stat, target_stat)


class TestSmartServerCheckout(TestCaseWithTransport):

    def test_heavyweight_checkout(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        for count in range(9):
            t.commit(message='commit %d' % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(['checkout', self.get_url('from'),
            'target'])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)

    def test_lightweight_checkout(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        for count in range(9):
            t.commit(message='commit %d' % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(['checkout', '--lightweight', self.get_url('from'),
            'target'])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(30, self.hpss_calls)
