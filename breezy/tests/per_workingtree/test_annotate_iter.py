# Copyright (C) 2009 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.annotate_iter'"""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestAnnotateIter(TestCaseWithWorkingTree):

    def make_single_rev_tree(self):
        builder = self.make_branch_builder('branch')
        revid = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        b = builder.get_branch()
        tree = b.create_checkout('tree', lightweight=True)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        return tree, revid

    def test_annotate_same_as_parent(self):
        tree, revid = self.make_single_rev_tree()
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid, 'initial content\n')],
                         annotations)

    def test_annotate_mod_from_parent(self):
        tree, revid = self.make_single_rev_tree()
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid, 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parents(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        revid1 = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        revid2 = builder.build_snapshot([revid1], [
            ('modify', ('file-id', 'initial content\ncontent in 2\n')),
            ])
        revid3 = builder.build_snapshot([revid1], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id=revid2, lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids([revid2, revid3])
        self.build_tree_contents([('tree/file',
                                   'initial content\ncontent in 2\n'
                                   'content in 3\nnew content\n')])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid1, 'initial content\n'),
                          (revid2, 'content in 2\n'),
                          (revid3, 'content in 3\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parent_no_file(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        revid1 = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ])
        revid2 = builder.build_snapshot([revid1], [
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        revid3 = builder.build_snapshot([revid1], [])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id=revid2, lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids([revid2, revid3])
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid2, 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_merge_parent_was_directory(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        revid1 = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ])
        revid2 = builder.build_snapshot([revid1], [
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        revid3 = builder.build_snapshot([revid1], [
            ('add', ('a_dir', 'file-id', 'directory', None)),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id=revid2, lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids([revid2, revid3])
        self.build_tree_contents([('tree/file',
                                   'initial content\nnew content\n')])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid2, 'initial content\n'),
                          ('current:', 'new content\n'),
                         ], annotations)

    def test_annotate_same_as_merge_parent(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        revid1 = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        revid2 = builder.build_snapshot([revid1], [
            ])
        revid3 = builder.build_snapshot([revid1], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id=revid2, lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids([revid2, revid3])
        self.build_tree_contents([('tree/file',
                                   'initial content\ncontent in 3\n')])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid1, 'initial content\n'),
                          (revid3, 'content in 3\n'),
                         ], annotations)

    def test_annotate_same_as_merge_parent_supersedes(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        revid1 = builder.build_snapshot(None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'initial content\n')),
            ])
        revid2 = builder.build_snapshot([revid1], [
            ('modify', ('file-id', 'initial content\nnew content\n')),
            ])
        revid3 = builder.build_snapshot([revid2], [
            ('modify', ('file-id', 'initial content\ncontent in 3\n')),
            ])
        revid4 = builder.build_snapshot([revid3], [
            ('modify', ('file-id', 'initial content\nnew content\n')),
            ])
        # In this case, the content locally is the same as content in basis
        # tree, but the merge revision states that *it* should win
        builder.finish_series()
        b = builder.get_branch()
        tree = b.create_checkout('tree', revision_id=revid2, lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.set_parent_ids([revid2, revid4])
        annotations = tree.annotate_iter('file')
        self.assertEqual([(revid1, 'initial content\n'),
                          (revid4, 'new content\n'),
                         ], annotations)

