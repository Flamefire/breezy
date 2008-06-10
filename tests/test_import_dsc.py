#    test_import_dsc.py -- Test importing .dsc files.
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

import gzip
import os
import shutil
import sys
import tarfile

from debian_bundle.changelog import Version, Changelog

from bzrlib.config import ConfigObj
from bzrlib.conflicts import TextConflict
from bzrlib.errors import FileExists, UncommittedChanges
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.builddeb.errors import ImportError, OnlyImportSingleDsc
from bzrlib.plugins.builddeb.import_dsc import (
        DscImporter,
        files_to_ignore,
        DistributionBranch,
        DistributionBranchSet,
        )

def write_to_file(filename, contents):
  f = open(filename, 'wb')
  try:
    f.write(contents)
  finally:
    f.close()

def append_to_file(filename, contents):
  f = open(filename, 'ab')
  try:
    f.write(contents)
  finally:
    f.close()

class TestDscImporter(TestCaseWithTransport):

  basedir = 'package'
  target = 'target'
  orig_1 = 'package_0.1.orig.tar.gz'
  orig_2 = 'package_0.2.orig.tar.gz'
  orig_3 = 'package_0.3.orig.tar.gz'
  diff_1 = 'package_0.1-1.diff.gz'
  diff_1b = 'package_0.1-2.diff.gz'
  diff_1c = 'package_0.1-3.diff.gz'
  diff_2 = 'package_0.2-1.diff.gz'
  diff_3 = 'package_0.3-1.diff.gz'
  dsc_1 = 'package_0.1-1.dsc'
  dsc_1b = 'package_0.1-2.dsc'
  dsc_1c = 'package_0.1-3.dsc'
  dsc_2 = 'package_0.2-1.dsc'
  dsc_3 = 'package_0.3-1.dsc'
  native_1 = 'package_0.1.tar.gz'
  native_2 = 'package_0.2.tar.gz'
  native_dsc_1 = 'package_0.1.dsc'
  native_dsc_2 = 'package_0.2.dsc'

  config_files = ['.bzr-builddeb/', '.bzr-builddeb/default.conf']

  def assertRulesExecutable(self, tree):
    """Checks that the debian/rules in the tree is executable"""
    tree.lock_read()
    try:
      self.assertTrue(tree.is_executable(tree.path2id('debian/rules')))
    finally:
      tree.unlock()

  def make_base_package(self):
    os.mkdir(self.basedir)
    write_to_file(os.path.join(self.basedir, 'README'), 'hello\n')
    write_to_file(os.path.join(self.basedir, 'CHANGELOG'), 'version 1\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'bad command\n')
    for filename in files_to_ignore:
      write_to_file(os.path.join(self.basedir, filename),
          "you ain't seen me, right?")

  def extend_base_package(self):
    write_to_file(os.path.join(self.basedir, 'NEWS'), 'new release\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'good command\n')
    write_to_file(os.path.join(self.basedir, 'from_debian'), 'from debian\n')
    for filename in files_to_ignore:
      os.unlink(os.path.join(self.basedir, filename))

  def extend_base_package2(self):
    write_to_file(os.path.join(self.basedir, 'NEW_IN_3'), 'new release\n')

  def make_orig_1(self):
    self.make_base_package()
    tar = tarfile.open(self.orig_1, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_orig_2(self):
    self.extend_base_package()
    tar = tarfile.open(self.orig_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_orig_3(self):
    self.extend_base_package2()
    tar = tarfile.open(self.orig_3, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_diff_1(self):
    diffdir = 'package-0.1'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                  'version 1-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'Makefile'), 'good command\n')
    write_to_file(os.path.join(diffdir, 'debian', 'rules'), '\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1))

  def make_diff_1b(self):
    diffdir = 'package-0.1'
    append_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                   'version 1-2\n')
    write_to_file(os.path.join(diffdir, 'debian', 'control'), 'package\n')
    os.unlink(os.path.join(diffdir, 'debian', 'install'))
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1b))

  def make_diff_1c(self):
    diffdir = 'package-0.1'
    append_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                   'version 1-3\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'from_debian'), 'from debian\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1c))

  def make_diff_2(self):
    diffdir = 'package-0.2'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                  'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'debian', 'rules'), '\n')
    for filename in files_to_ignore:
      write_to_file(os.path.join(diffdir, filename),
          "i'm like some annoying puppy")
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_2))

  def make_diff_3(self):
    diffdir = 'package-0.3'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, '.bzr'))
    write_to_file(os.path.join(diffdir, '.bzr', 'branch-format'),
        'broken format')
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
          'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\nversion 3-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_3))

  def make_dsc(self, filename, version, file1, extra_files=[],
               package='package'):
    write_to_file(filename, """Format: 1.0
Source: %s
Version: %s
Binary: package
Maintainer: maintainer <maint@maint.org>
Architecture: any
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 5.0.0)
Files:
 8636a3e8ae81664bac70158503aaf53a 1328218 %s
""" % (package, version, os.path.basename(file1)))
    i = 1
    for extra_file in extra_files:
      append_to_file(filename,
                     " 1acd97ad70445afd5f2a64858296f21%d 20709 %s\n" % \
                     (i, os.path.basename(extra_file)))
      i += 1

  def make_dsc_1(self):
    self.make_orig_1()
    self.make_diff_1()
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1])

  def make_dsc_1b(self):
    self.make_diff_1b()
    self.make_dsc(self.dsc_1b, '0.1-2', self.diff_1b)

  def make_dsc_1b_repeated_orig(self):
    self.make_diff_1b()
    self.make_dsc(self.dsc_1b, '0.1-2', self.orig_1, [self.diff_1b])

  def make_dsc_1c(self):
    self.make_diff_1c()
    self.make_dsc(self.dsc_1c, '0.1-3', self.diff_1c)

  def make_dsc_2(self):
    self.make_orig_2()
    self.make_diff_2()
    self.make_dsc(self.dsc_2, '0.2-1', self.orig_2, [self.diff_2])

  def make_dsc_3(self):
    self.make_orig_3()
    self.make_diff_3()
    self.make_dsc(self.dsc_3, '0.3-1', self.orig_3, [self.diff_3])

  def import_dsc_1(self):
    self.make_dsc_1()
    DscImporter([self.dsc_1]).import_dsc(self.target)

  def import_dsc_1b(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_1b_repeated_diff(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_1c(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    DscImporter([self.dsc_1, self.dsc_1c, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_2(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1c, self.dsc_2])
    importer.import_dsc(self.target)

  def import_dsc_2_repeated_orig(self):
    self.make_dsc_1()
    self.make_dsc_1b_repeated_orig()
    self.make_dsc_1c()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1c, self.dsc_2])
    importer.import_dsc(self.target)

  def test_import_dsc_target_extant(self):
    os.mkdir(self.target)
    write_to_file('package_0.1.dsc', '')
    importer = DscImporter([self.dsc_1])
    self.assertRaises(FileExists, importer.import_dsc, self.target)

  def test_import_one_dsc_tree(self):
    self.import_dsc_1()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_one_dsc_history(self):
    self.import_dsc_1()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    expected_modified = ['Makefile']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    tag = tree.branch.tags.lookup_tag('upstream-0.1')
    self.assertEqual(tag, rh[0])

  def test_import_two_dsc_one_upstream_tree(self):
    self.import_dsc_1b()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_two_dsc_one_upstream_history(self):
    self.import_dsc_1b()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_two_dsc_one_upstream_history_repeated_diff(self):
    self.import_dsc_1b_repeated_diff()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_three_dsc_one_upstream_tree(self):
    self.import_dsc_1c()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/control',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\nversion 1-3\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_three_dsc_one_upstream_history(self):
    self.import_dsc_1c()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 4)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    self.check_revision_message(tree, rh[3],
                          'merge packaging changes from %s' % self.diff_1c)
    prev_tree = tree.branch.repository.revision_tree(rh[2])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/install', 'from_debian']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_three_dsc_two_upstream_tree(self):
    self.import_dsc_2()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                     'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def assertContentsAre(self, filename, expected_contents):
    f = open(filename)
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, expected_contents,
                     "Contents of %s are not as expected" % filename)

  def test_import_four_dsc_two_upstream_history(self):
    self.import_dsc_2()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'import upstream from %s' % self.orig_2)
    self.check_revision_message(tree, rh[2],
                         'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.check_revision_message(tree, parents[1],
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    # Check the diff against last packaging version
    last_package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(last_package_tree)
    expected_added = ['NEWS']
    expected_removed = ['debian/control']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(last_package_tree)

  def test_import_dsc_restrictions_on_dscs(self):
    """Test that errors are raised for confusing sets of .dsc files."""
    self.make_dsc(self.dsc_1, '0.1-1', self.diff_1)
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1)
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1, self.diff_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.orig_1, self.diff_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1])
    self.make_dsc(self.dsc_1b, '0.1-2', self.diff_1b, package='otherpackage')
    importer = DscImporter([self.dsc_1, self.dsc_1b])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1', self.diff_1b, [self.orig_1,
                                                    self.native_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1', self.native_1, [self.native_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)

  def test_import_four_dsc_two_upstream_history_repeated_orig(self):
    self.import_dsc_2_repeated_orig()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0], 'import upstream from %s' % \
                                self.orig_1)
    self.check_revision_message(tree, rh[1], 'import upstream from %s' % \
                                self.orig_2)
    self.check_revision_message(tree, rh[2],
                         'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.assertEqual(tree.branch.repository.get_revision(parents[1]).message,
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    # Check the diff against last packaging version
    last_package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(last_package_tree)
    expected_added = ['NEWS']
    expected_removed = ['debian/control']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(last_package_tree)

  def test_import_dsc_different_dir(self):
    source = 'source'
    os.mkdir(source)
    self.diff_1 = os.path.join(source, self.diff_1)
    self.orig_1 = os.path.join(source, self.orig_1)
    self.dsc_1 = os.path.join(source, self.dsc_1)
    self.import_dsc_1()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertRulesExecutable(tree)

  def _add_debian_to_native(self):
    os.mkdir(os.path.join(self.basedir, 'debian'))
    write_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                  'version 1\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')

  def _make_native(self, tarball_name, dsc_name):
    tar = tarfile.open(tarball_name, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(dsc_name, '0.1', tarball_name)


  def make_native_dsc_1(self):
    self.make_base_package()
    self._add_debian_to_native()
    self._make_native(self.native_1, self.native_dsc_1)

  def make_native_dsc_2(self):
    self.extend_base_package()
    append_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                   'version 2\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')
    tar = tarfile.open(self.native_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_2, '0.2', self.native_2)

  def make_native_dsc_2_after_non_native(self):
    self.extend_base_package()
    os.mkdir(os.path.join(self.basedir, 'debian'))
    write_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                  'version 1\nversion 2\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')
    tar = tarfile.open(self.native_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_2, '0.2', self.native_2)

  def test_import_dsc_native_single(self):
    self.make_native_dsc_1()
    importer = DscImporter([self.native_dsc_1])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/rules'] + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 1)
    self.check_revision_message(tree, rh[0], "import package from %s" % \
                     os.path.basename(self.native_1))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    self.check_is_native_in_config(tree)
    self.assertRulesExecutable(tree)

  def test_import_dsc_native_double(self):
    self.make_native_dsc_1()
    self.make_native_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/rules'] \
                   + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0], "import package from %s" % \
                     os.path.basename(self.native_1))
    self.check_revision_message(tree, rh[1], "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    self.check_is_native_in_config(tree)
    old_tree = tree.branch.repository.revision_tree(rh[0])
    self.check_is_native_in_config(old_tree)
    changes = tree.changes_from(old_tree)
    expected_added = ['NEWS', 'from_debian']
    expected_modified = ['Makefile', 'debian/changelog']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(old_tree)

  def check_revision_message(self, tree, revision, expected_message):
    rev = tree.branch.repository.get_revision(revision)
    self.assertEqual(rev.message, expected_message)

  def test_non_native_to_native(self):
    self.make_dsc_1()
    self.make_native_dsc_2_after_non_native()
    importer = DscImporter([self.dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/rules'] \
                   + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0], "import upstream from %s" % \
                     os.path.basename(self.orig_1))
    self.check_revision_message(tree, rh[1], "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.check_revision_message(tree, parents[1],
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_1))
    up_tree = tree.branch.repository.revision_tree(rh[0])
    changes = tree.changes_from(up_tree)
    expected_added = ['NEWS', 'debian/', 'debian/changelog', 'debian/rules',
                      'from_debian']
    expected_added += self.config_files
    self.check_changes(changes, added=expected_added, modified=['Makefile'])
    package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(package_tree)
    expected_added = ['NEWS', 'from_debian'] + self.config_files
    expected_modified = ['debian/changelog']
    expected_removed = ['debian/install']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified, removed=expected_removed)
    self.check_is_not_native_in_config(up_tree)
    self.check_is_not_native_in_config(package_tree)
    self.check_is_native_in_config(tree)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(package_tree)

  def check_changes(self, changes, added=[], removed=[], modified=[],
                    renamed=[]):
    exp_added = set(added)
    exp_removed = set(removed)
    exp_modified = set(modified)
    exp_renamed = set(renamed)

    def make_set(list):
      output = set()
      for item in list:
        if item[2] == 'directory':
          output.add(item[0] + '/')
        else:
          output.add(item[0])
      return output

    real_added = make_set(changes.added)
    real_removed = make_set(changes.removed)
    real_modified = make_set(changes.modified)
    real_renamed = make_set(changes.renamed)
    missing_added = exp_added.difference(real_added)
    missing_removed = exp_removed.difference(real_removed)
    missing_modified = exp_modified.difference(real_modified)
    missing_renamed = exp_renamed.difference(real_renamed)
    extra_added = real_added.difference(exp_added)
    extra_removed = real_removed.difference(exp_removed)
    extra_modified = real_modified.difference(exp_modified)
    extra_renamed = real_renamed.difference(exp_renamed)
    if len(missing_added) > 0:
      self.fail("Some expected paths not found added in the changes: %s" % \
                 str(missing_added))
    if len(missing_removed) > 0:
      self.fail("Some expected paths not found removed in the changes: %s" % \
                 str(missing_removed))
    if len(missing_modified) > 0:
      self.fail("Some expected paths not found modified in the changes: %s" % \
                 str(missing_modified))
    if len(missing_renamed) > 0:
      self.fail("Some expected paths not found renamed in the changes: %s" % \
                 str(missing_renamed))
    if len(extra_added) > 0:
      self.fail("Some extra paths found added in the changes: %s" % \
                 str(extra_added))
    if len(extra_removed) > 0:
      self.fail("Some extra paths found removed in the changes: %s" % \
                 str(extra_removed))
    if len(extra_modified) > 0:
      self.fail("Some extra paths found modified in the changes: %s" % \
                 str(extra_modified))
    if len(extra_renamed) > 0:
      self.fail("Some extra paths found renamed in the changes: %s" % \
                 str(extra_renamed))

  def test_native_to_non_native(self):
    self.make_native_dsc_1()
    shutil.rmtree(os.path.join(self.basedir, 'debian'))
    self.make_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                     "import package from %s" % \
                     os.path.basename(self.native_1))
    self.check_revision_message(tree, rh[1],
                     "import upstream from %s" % \
                     os.path.basename(self.orig_2))
    self.check_revision_message(tree, rh[2],
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    up_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(up_tree)
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    native_tree = tree.branch.repository.revision_tree(rh[0])
    changes = up_tree.changes_from(native_tree)
    expected_added = ['NEWS', 'from_debian']
    expected_modified = ['Makefile']
    expected_removed = ['debian/', 'debian/changelog', 'debian/rules'] \
                       + self.config_files
    self.check_changes(changes, added=expected_added, removed=expected_removed,
                       modified=expected_modified)
    # FIXME: Should changelog etc. be added/removed or not?
    changes = tree.changes_from(native_tree)
    expected_added = ['NEWS', 'debian/', 'debian/install', 'from_debian',
                      'debian/changelog', 'debian/rules']
    expected_modified = ['Makefile']
    expected_removed = ['debian/', 'debian/changelog', 'debian/rules'] \
                       + self.config_files
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified, removed=expected_removed)
    self.check_is_native_in_config(native_tree)
    self.check_is_not_native_in_config(up_tree)
    self.check_is_not_native_in_config(tree)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(native_tree)

  def _get_tree_default_config(self, tree, fail_on_none=True):
    config_file_id = tree.path2id('.bzr-builddeb/default.conf')
    if config_file_id is None:
      if fail_on_none:
        self.fail("The tree has no config file")
      else:
        return None
    config_file = tree.get_file_text(config_file_id).split('\n')
    config = ConfigObj(config_file)
    return config

  def check_is_native_in_config(self, tree):
    tree.lock_read()
    try:
      config = self._get_tree_default_config(tree)
      self.assertEqual(bool(config['BUILDDEB']['native']), True)
    finally:
      tree.unlock()

  def check_is_not_native_in_config(self, tree):
    config = self._get_tree_default_config(tree, fail_on_none=False)
    if config is not None:
      self.assertEqual(bool(config['BUILDDEB']['native']), False)

  def test_import_incremental_simple(self):
    # set up the branch using a simple single version non-native import.
    self.import_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1b]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    current_tree = tree.branch.repository.revision_tree(rh[1])
    changes = prev_tree.changes_from(current_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)
    self.assertEqual(len(tree.conflicts()), 0)
    changes = tree.changes_from(tree.basis_tree())
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)

  def test_import_incremental_multiple_dscs_prohibited(self):
    self.import_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1b, self.dsc_2])
    self.assertRaises(OnlyImportSingleDsc, importer.incremental_import_dsc,
      self.target)

  def test_import_incremental_working_tree_changes(self):
    self.import_dsc_1()
    self.make_dsc_1b()
    self.build_tree([os.path.join(self.target, 'a')])
    tree = WorkingTree.open(self.target)
    tree.add(['a'])
    importer = DscImporter([self.dsc_1b])
    self.assertRaises(UncommittedChanges, importer.incremental_import_dsc,
            self.target)

  def test_incremental_with_upstream(self):
    self.import_dsc_1()
    self.make_dsc_2()
    DscImporter([self.dsc_2]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\n=======\nversion 1-1\nversion 1-2\n'
        'version 1-3\nversion 2-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_2)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    current_tree = tree.branch.repository.revision_tree(parents[0])
    changes = prev_tree.changes_from(current_tree)
    expected_added = ['from_debian', 'NEWS']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=[], modified=expected_modified)
    self.assertRulesExecutable(prev_tree)
    self.assertEqual(len(tree.conflicts()), 1)
    self.assertTrue(isinstance(tree.conflicts()[0], TextConflict))
    self.assertEqual(tree.conflicts()[0].path, 'debian/changelog')
    changes = tree.changes_from(tree.basis_tree())
    self.check_changes(changes, added=expected_added,
                       removed=[], modified=expected_modified)
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)
    new_upstream_tree = tree.branch.repository.revision_tree(merged_parents[0])
    new_upstream_parents = new_upstream_tree.get_parent_ids()
    self.assertEqual(len(new_upstream_parents), 1)
    self.assertEqual(new_upstream_parents[0], rh[0])

  def test_incremental_with_upstream_older_than_all_in_branch(self):
    self.make_dsc_1()
    self.make_dsc_2()
    DscImporter([self.dsc_2]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    DscImporter([self.dsc_1]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n'
        '=======\nversion 1-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_2)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_2)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_1)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_1)

  def test_incremental_with_upstream_older_than_lastest_in_branch(self):
    self.make_dsc_1()
    self.make_dsc_2()
    self.make_dsc_3()
    DscImporter([self.dsc_1, self.dsc_3]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    DscImporter([self.dsc_2,]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'NEW_IN_3', 'debian/', 'debian/changelog',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n'
        'version 3-1\n=======\nversion 1-1\nversion 1-2\nversion 1-3\n'
        'version 2-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'import upstream from %s' % self.orig_3)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_3)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[2])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_2)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)
    new_upstream_tree = tree.branch.repository.revision_tree(merged_parents[0])
    new_upstream_parents = new_upstream_tree.get_parent_ids()
    self.assertEqual(len(new_upstream_parents), 1)
    self.assertEqual(new_upstream_parents[0], rh[0])
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)

  def test_import_no_prefix(self):
    write_to_file('README', 'hello\n')
    write_to_file('NEWS', 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.add('./', recursive=False)
      tar.add('README')
      tar.add('NEWS')
    finally:
      tar.close()
      os.unlink('README')
      os.unlink('NEWS')
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)

  def test_import_dot_prefix(self):
    write_to_file('README', 'hello\n')
    write_to_file('NEWS', 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.addfile(_TarInfo('./'))
      tar.addfile(_TarInfo('./README'))
      tar.addfile(_TarInfo('./NEWS'))
    finally:
      tar.close()
      os.unlink('README')
      os.unlink('NEWS')
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failIfExists(os.path.join(self.target, 'ADME'))
    self.failUnlessExists(os.path.join(self.target, 'README'))

  def test_import_dot_and_prefix(self):
    dir = 'dir'
    os.mkdir(dir)
    write_to_file(os.path.join(dir, 'README'), 'hello\n')
    write_to_file(os.path.join(dir, 'NEWS'), 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.addfile(_TarInfo('./'))
      tar.addfile(_TarInfo(dir))
      tar.addfile(_TarInfo(os.path.join(dir, 'README')))
      tar.addfile(_TarInfo(os.path.join(dir, 'NEWS')))
    finally:
      tar.close()
      shutil.rmtree(dir)
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failIfExists(os.path.join(self.target, dir))

  def test_import_absolute_path(self):
    dir = 'dir'
    os.mkdir(dir)
    write_to_file(os.path.join(dir, 'README'), 'hello\n')
    write_to_file(os.path.join(dir, 'NEWS'), 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.addfile(_TarInfo(dir))
      tar.addfile(_TarInfo('/' + os.path.join(dir, 'README')))
      tar.addfile(_TarInfo(os.path.join(dir, 'NEWS')))
    finally:
      tar.close()
      shutil.rmtree(dir)
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failIfExists(os.path.join(self.target, dir))
    self.failUnlessExists(os.path.join(self.target, 'README'))
    self.failUnlessExists(os.path.join(self.target, 'NEWS'))

  def test_import_with_rcs(self):
    write_to_file('README', 'hello\n')
    write_to_file('README,v', 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.add('README')
      tar.add('README,v')
    finally:
      tar.close()
      os.unlink('README')
      os.unlink('README,v')
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failIfExists(os.path.join(self.target, 'README,v'))

  def test_patch_with_rcs(self):
    self.make_orig_1()
    diffdir = 'package-0.1'
    shutil.copytree(self.basedir, diffdir)
    f = gzip.open(self.diff_1, 'w')
    try:
      f.write(
"""diff -Nru package/file,v package-0.2/file,v
--- package/file,v      1970-01-01 01:00:00.000000000 +0100
+++ package-0.2/file,v  2008-01-25 12:48:26.823475582 +0000
@@ -0,0 +1 @@
+with a passion
\ No newline at end of file
diff -Nru package/file package-0.2/file
--- package/file      1970-01-01 01:00:00.000000000 +0100
+++ package-0.2/file  2008-01-25 12:48:26.823475582 +0000
@@ -0,0 +1 @@
+with a passion
\ No newline at end of file
""")
    finally:
      f.close()
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1])
    DscImporter([self.dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failIfExists(os.path.join(self.target, 'changelog'))
    self.failIfExists(os.path.join(self.target, 'changelog,v'))

  def test_import_extra_slash(self):
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.addfile(_TarInfo('root//'))
      tar.addfile(_TarInfo('root//README'))
      tar.addfile(_TarInfo('root//NEWS'))
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)

  def test_import_hardlink(self):
    write_to_file('README', 'hello\n')
    os.system('ln README NEWS')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.add('./', recursive=False)
      tar.add('./README')
      tar.add('./NEWS')
    finally:
      tar.close()
      os.unlink('README')
      os.unlink('NEWS')
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    self.failUnlessExists(os.path.join(self.target, 'NEWS'))
    self.failUnlessExists(os.path.join(self.target, 'README'))


class _TarInfo(tarfile.TarInfo):
    """Subclass TarInfo to stop it normalising its path. Sorry Mum."""

if sys.version > (2, 4):
        def tobuf(self, posix=False):
            """Return a tar header as a string of 512 byte blocks.
            """
            buf = ""
            type = self.type
            prefix = ""

            if self.name.endswith("/"):
                type = tarfile.DIRTYPE

            name = self.name

            if type == tarfile.DIRTYPE:
                # directories should end with '/'
                name += "/"

            linkname = self.linkname
            if linkname:
                # if linkname is empty we end up with a '.'
                linkname = os.path.normpath(linkname)

            if posix:
                if self.size > tarfile.MAXSIZE_MEMBER:
                    raise ValueError("file is too large (>= 8 GB)")

                if len(self.linkname) > tarfile.LENGTH_LINK:
                    raise ValueError("linkname is too long (>%d)" \
                            % (tarfile.LENGTH_LINK))

                if len(name) > tarfile.LENGTH_NAME:
                    prefix = name[:tarfile.LENGTH_PREFIX + 1]
                    while prefix and prefix[-1] != "/":
                        prefix = prefix[:-1]

                    name = name[len(prefix):]
                    prefix = prefix[:-1]

                    if not prefix or len(name) > tarfile.LENGTH_NAME:
                        raise ValueError("name is too long")

            else:
                if len(self.linkname) > tarfile.LENGTH_LINK:
                    buf += self._create_gnulong(self.linkname,
                                                tarfile.GNUTYPE_LONGLINK)

                if len(name) > tarfile.LENGTH_NAME:
                    buf += self._create_gnulong(name, tarfile.GNUTYPE_LONGNAME)

            parts = [
                tarfile.stn(name, 100),
                tarfile.itn(self.mode & 07777, 8, posix),
                tarfile.itn(self.uid, 8, posix),
                tarfile.itn(self.gid, 8, posix),
                tarfile.itn(self.size, 12, posix),
                tarfile.itn(self.mtime, 12, posix),
                "        ", # checksum field
                type,
                tarfile.stn(self.linkname, 100),
                tarfile.stn(tarfile.MAGIC, 6),
                tarfile.stn(tarfile.VERSION, 2),
                tarfile.stn(self.uname, 32),
                tarfile.stn(self.gname, 32),
                tarfile.itn(self.devmajor, 8, posix),
                tarfile.itn(self.devminor, 8, posix),
                tarfile.stn(prefix, 155)
            ]

            buf += "".join(parts).ljust(tarfile.BLOCKSIZE, tarfile.NUL)
            chksum = tarfile.calc_chksums(buf[-tarfile.BLOCKSIZE:])[0]
            buf = buf[:-364] + "%06o\0" % chksum + buf[-357:]
            self.buf = buf
            return buf

# vim: sw=2 sts=2 ts=2 

class DistributionBranchTests(TestCaseWithTransport):

    def setUp(self):
        super(DistributionBranchTests, self).setUp()
        self.tree1 = self.make_branch_and_tree('unstable')
        self.up_tree1 = self.make_branch_and_tree('unstable-upstream')
        self.name1 = "debian-unstable"
        self.db1 = DistributionBranch(self.name1, self.tree1, self.up_tree1)
        self.tree2 = self.make_branch_and_tree('experimental')
        self.up_tree2 = self.make_branch_and_tree('experimental-upstream')
        self.name2 = "debian-experimental"
        self.db2 = DistributionBranch(self.name2, self.tree2, self.up_tree2)
        self.tree3 = self.make_branch_and_tree('gutsy')
        self.up_tree3 = self.make_branch_and_tree('gutsy-upstream')
        self.name3 = "ubuntu-gutsy"
        self.db3 = DistributionBranch(self.name3, self.tree3, self.up_tree3)
        self.tree4 = self.make_branch_and_tree('hardy')
        self.up_tree4 = self.make_branch_and_tree('hardy-upstream')
        self.name4 = "ubuntu-hardy"
        self.db4 = DistributionBranch(self.name4, self.tree4, self.up_tree4)
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
        self.assertEqual(db.name, self.name1)
        self.assertEqual(db.tree, self.tree1)
        self.assertEqual(db.upstream_tree, self.up_tree1)

    def test_tag_name(self):
        db = self.db1
        version_no = "0.1-1"
        version = Version(version_no)
        self.assertEqual(db.tag_name(version),
                self.name1 + "-" + version_no)

    def test_upstream_tag_name(self):
        db = self.db1
        upstream_v_no = "0.1"
        version_no = upstream_v_no + "-1"
        version = Version(version_no)
        self.assertEqual(db.upstream_tag_name(version),
                "upstream-" + self.name1 + "-" + upstream_v_no)

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
        version = Version("0.1-1")
        revid = tree.commit("one")
        db.tag_upstream_version(version)
        tag_name = db.upstream_tag_name(version)
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

    def test_has_upstream_version(self):
        db = self.db1
        version = Version("0.1-1")
        self.assertFalse(db.has_upstream_version(version))
        self.assertFalse(db.has_upstream_version(version, self.fake_md5_1))
        self.do_commit_with_md5(self.up_tree1, "one", self.fake_md5_1)
        db.tag_upstream_version(version)
        self.assertTrue(db.has_upstream_version(version))
        self.assertTrue(db.has_upstream_version(version, self.fake_md5_1))
        self.assertFalse(db.has_upstream_version(version, self.fake_md5_2))
        version = Version("0.1-2")
        self.assertTrue(db.has_upstream_version(version))
        self.assertTrue(db.has_upstream_version(version, self.fake_md5_1))
        self.assertFalse(db.has_upstream_version(version, self.fake_md5_2))
        version = Version("0.2-1")
        self.assertFalse(db.has_upstream_version(version))
        self.assertFalse(db.has_upstream_version(version, self.fake_md5_1))
        self.assertFalse(db.has_upstream_version(version, self.fake_md5_2))

    def test_revid_of_version(self):
        db = self.db1
        tree = self.tree1
        version = Version("0.1-1")
        revid = tree.commit("one")
        db.tag_version(version)
        self.assertEqual(db.revid_of_version(version), revid)

    def test_revid_of_upstream_version(self):
        db = self.db1
        tree = self.up_tree1
        version = Version("0.1-1")
        revid = tree.commit("one")
        db.tag_upstream_version(version)
        self.assertEqual(db.revid_of_upstream_version(version), revid)

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
        db.tag_upstream_version(version1)
        self.assertEqual(db.get_parents_with_upstream(version1, [version1]),
                [up_revid])
        db = self.db2
        self.up_tree2.pull(self.up_tree1.branch)
        db.tag_upstream_version(version1)
        self.assertEqual(db.get_parents_with_upstream(version1, [version1]),
                [up_revid])

    def test_get_parents_with_upstream_second_version(self):
        db = self.db1
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        revid1 = self.tree1.commit("one")
        db.tag_version(version1)
        up_revid = self.up_tree1.commit("upstream one")
        db.tag_upstream_version(version1)
        # No upstream parent
        self.assertEqual(db.get_parents_with_upstream(version2,
                    [version2, version1]), [revid1])

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
        self.db1.tag_upstream_version(version1)
        self.db2.tag_upstream_version(version2)
        versions = [version3, version1, version2]
        # No upstream parent
        self.assertEqual(self.db2.get_parents_with_upstream(version3,
                    versions), [revid2, revid1])

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
        self.db1.tag_upstream_version(version1)
        self.db2.tag_upstream_version(version2)
        versions = [version3, version2, version1]
        # No upstream parent
        self.assertEqual(self.db1.get_parents_with_upstream(version3,
                    versions), [revid1, revid2])

    def test_get_parents_with_upstream_new_upstream_import(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-0ubuntu1")
        revid1 = self.tree1.commit("one")
        self.tree2.pull(self.tree1.branch)
        self.db1.tag_version(version1)
        self.db2.tag_version(version1)
        up_revid1 = self.up_tree1.commit("upstream one")
        up_revid2 = self.up_tree2.commit("upstream two")
        self.db1.tag_upstream_version(version1)
        self.db2.tag_upstream_version(version2)
        versions = [version2, version1]
        # Upstream parent as it is new upstream version
        self.assertEqual(self.db2.get_parents_with_upstream(version2,
                    versions), [revid1, up_revid2])

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
        self.db1.tag_upstream_version(version1)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version4)
        versions = [version4, version3, version2, version1]
        # no upstream parent as the lesser branch has already merged it
        self.assertEqual(self.db2.get_parents_with_upstream(version4,
                    versions), [revid2, revid3])

    def test_get_parents_with_upstream_force_upstream(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-1ubuntu1")
        revid1 = self.tree1.commit("one")
        self.db1.tag_version(version1)
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1)
        up_revid2 = self.up_tree2.commit("different upstream one")
        self.db2.tag_upstream_version(version2)
        versions = [version2, version1]
        # a previous test checked that this wouldn't give an
        # upstream parent, but we are requiring one.
        self.assertEqual(self.db2.get_parents_with_upstream(version2,
                    versions, force_upstream_parent=True),
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
        self.db1.tag_upstream_version(version1)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2)
        versions = [version3, version2, version1]
        # This is a sync but we are diverged so we should get two
        # parents
        self.assertEqual(self.db2.get_parents_with_upstream(version3,
                    versions), [revid2, revid3])

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
        self.db1.tag_upstream_version(version1)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3)
        versions = [version3, version2, version1]
        # This a sync, but we are diverged, so we should get two
        # parents. There should be no upstream as the synced
        # version will already have it.
        self.assertEqual(self.db2.get_parents_with_upstream(version3,
                    versions), [revid2, revid3])

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
        self.db1.tag_upstream_version(version1)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version2)
        up_revid2 = self.up_tree1.commit("upstream two")
        self.db1.tag_upstream_version(version3)
        versions = [version3, version2, version1]
        up_revid3 = self.up_tree2.commit("different upstream two")
        self.db2.tag_upstream_version(version3)
        versions = [version3, version2, version1]
        # test_get_parents_with_upstream_sync_new_upstream
        # checks that there is not normally an upstream parent
        # when we fake-sync, but we are forcing one here.
        #TODO: should the upstream parent be second or third?
        self.assertEqual(self.db2.get_parents_with_upstream(version3,
                    versions, force_upstream_parent=True),
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
        branch = self.db2.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from(version1,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        branch = self.db1.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        self.do_commit_with_md5(self.up_tree1, "one", self.fake_md5_1)
        self.db1.tag_upstream_version(version1)
        # Version and md5 available, so we get the correct branch.
        branch = self.db2.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, self.db1)
        # Otherwise (different version or md5) then we get None
        branch = self.db2.branch_to_pull_upstream_from(version1,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from(version2,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        branch = self.db2.branch_to_pull_upstream_from(version2,
                self.fake_md5_2)
        self.assertEqual(branch, None)
        # And we don't get a branch for the one that already has
        # the version
        branch = self.db1.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)
        self.up_tree2.pull(self.up_tree1.branch)
        self.db2.tag_upstream_version(version1)
        # And we get the greatest branch when two lesser branches
        # have what we are looking for.
        branch = self.db3.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, self.db2)
        # If the branches have diverged then we don't get a branch.
        self.up_tree3.commit("three")
        branch = self.db3.branch_to_pull_upstream_from(version1,
                self.fake_md5_1)
        self.assertEqual(branch, None)

    def test_pull_from_lesser_branch_no_upstream(self):
        version = Version("0.1-1")
        self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version)
        up_revid = self.do_commit_with_md5(self.up_tree2, "upstream two",
                self.fake_md5_1)
        self.db2.tag_upstream_version(version)
        revid = self.do_commit_with_md5(self.tree1, "one", self.fake_md5_2)
        self.db1.tag_version(version)
        self.assertNotEqual(self.tree2.branch.last_revision(), revid)
        self.db2.pull_version_from_branch(self.db1, version)
        self.assertEqual(self.tree2.branch.last_revision(), revid)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.revid_of_version(version), revid)
        self.assertEqual(self.db2.revid_of_upstream_version(version),
                up_revid)

    def test_pull_from_lesser_branch_with_upstream(self):
        version = Version("0.1-1")
        up_revid = self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version)
        revid = self.do_commit_with_md5(self.tree1, "one", self.fake_md5_2)
        self.db1.tag_version(version)
        self.assertNotEqual(self.tree2.branch.last_revision(), revid)
        self.assertNotEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.db2.pull_version_from_branch(self.db1, version)
        self.assertEqual(self.tree2.branch.last_revision(), revid)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.revid_of_version(version), revid)
        self.assertEqual(self.db2.revid_of_upstream_version(version),
                up_revid)

    def test_pull_upstream_from_branch(self):
        version = Version("0.1-1")
        up_revid = self.do_commit_with_md5(self.up_tree1, "upstream one",
                self.fake_md5_1)
        self.db1.tag_upstream_version(version)
        self.assertNotEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.db2.pull_upstream_from_branch(self.db1, version)
        self.assertEqual(self.up_tree2.branch.last_revision(), up_revid)
        self.assertEqual(self.db2.revid_of_upstream_version(version),
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

    def test_import_upstream(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.build_orig()
        self.db1.import_upstream(builder.orig_name(), version,
                self.fake_md5_1)
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 1)
        self.assertEqual(self.db1.revid_of_upstream_version(version), rh[0])
        rev = branch.repository.get_revision(rh[0])
        self.assertEqual(rev.message,
                "Import upstream from %s" % builder.orig_name())
        self.assertEqual(rev.properties['deb-md5'], self.fake_md5_1)

    def test_import_upstream_on_another(self):
        version1 = Version("0.1-1")
        version2 = Version("0.1-2")
        name = "package"
        builder = SourcePackageBuilder(name, version1)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("COPYING")
        builder.build_orig()
        self.db1.import_upstream(builder.orig_name(), version1,
                self.fake_md5_1)
        builder = SourcePackageBuilder(name, version2)
        builder.add_upstream_file("README", "Now even better\n")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("NEWS")
        builder.build_orig()
        self.db1.import_upstream(builder.orig_name(), version2,
                self.fake_md5_2)
        tree = self.up_tree1
        branch = tree.branch
        rh = branch.revision_history()
        self.assertEqual(len(rh), 2)
        self.assertEqual(self.db1.revid_of_upstream_version(version2), rh[1])
        rev = branch.repository.get_revision(rh[1])
        self.assertEqual(rev.message,
                "Import upstream from %s" % builder.orig_name())
        self.assertEqual(rev.properties['deb-md5'], self.fake_md5_2)
        rev_tree1 = branch.repository.revision_tree(rh[0])
        rev_tree2 = branch.repository.revision_tree(rh[1])
        changes = rev_tree2.changes_from(rev_tree1)
        self.check_changes(changes, added=["NEWS"], removed=["COPYING"],
                modified=["README"])

    def test_import_package_init_from_other(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        up_revid1 = self.up_tree1.commit("upstream one")
        self.db1.tag_upstream_version(version1)
        self.tree1.pull(self.up_tree1.branch)
        revid1 = self.tree1.commit("one")
        self.db1.tag_version(version1)
        builder = SourcePackageBuilder("package", version2)
        cl = Changelog()
        cl.new_block(package="package", version=version1,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        cl.new_block(package="package", version=version2,
                distributions="experimental", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder.add_debian_file("debian/changelog", str(cl))
        builder.build()
        self.db2.import_package(builder.dsc_name())
        self.assertEqual(len(self.up_tree2.branch.revision_history()), 2)
        self.assertEqual(len(self.tree2.branch.revision_history()), 3)

    def import_package_single(self):
        version1 = Version("0.1-1")
        builder = SourcePackageBuilder("package", version1)
        cl = Changelog()
        cl.new_block(package="package", version=version1,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder.add_upstream_file("README", "foo")
        builder.add_debian_file("debian/changelog", str(cl))
        builder.build()
        self.db1.import_package(builder.dsc_name())
        self.assertEqual(len(self.up_tree1.branch.revision_history()), 1)
        self.assertEqual(len(self.tree1.branch.revision_history()), 2)

    def test_import_package_double(self):
        version1 = Version("0.1-1")
        version2 = Version("0.2-1")
        builder = SourcePackageBuilder("package", version1)
        cl = Changelog()
        cl.new_block(package="package", version=version1,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder.add_upstream_file("README", "foo")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("NEWS")
        builder.add_debian_file("debian/changelog", str(cl))
        builder.add_debian_file("COPYING", "Don't do it\n")
        builder.build()
        self.db1.import_package(builder.dsc_name())
        cl.new_block(package="package", version=version2,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder = SourcePackageBuilder("package", version2)
        builder.add_upstream_file("README", "bar")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("COPYING", "Please do\n")
        builder.add_upstream_file("src.c")
        builder.add_debian_file("debian/changelog", str(cl))
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
                added=["debian/", "debian/changelog", "COPYING"])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["debian/changelog", "COPYING", "README"],
                added=["src.c"], removed=["NEWS"])
        self.check_changes(rev_tree2.changes_from(up_rev_tree2),
                added=["debian/", "debian/changelog"])
        self.check_changes(up_rev_tree2.changes_from(rev_tree1),
                added=["src.c"],
                removed=["NEWS", "debian/", "debian/changelog"],
                modified=["README", "COPYING"])

    def test_import_two_roots(self):
        version1 = Version("0.1-0ubuntu1")
        version2 = Version("0.1-1")
        builder = SourcePackageBuilder("package", version1)
        cl = Changelog()
        cl.new_block(package="package", version=version1,
                distributions="intrepid", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder.add_upstream_file("README", "foo")
        builder.add_debian_file("debian/changelog", str(cl))
        builder.build()
        self.db2.import_package(builder.dsc_name())
        cl = Changelog()
        cl.new_block(package="package", version=version2,
                distributions="unstable", urgency="low",
                author="Maint <maint@maint.org",
                date="Wed, 19 Mar 2008 21:27:37 +0000")
        cl.add_change("  * foo")
        builder = SourcePackageBuilder("package", version2)
        builder.add_upstream_file("README", "bar")
        builder.add_debian_file("debian/changelog", str(cl))
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
                added=["debian/", "debian/changelog"])
        self.check_changes(rev_tree2.changes_from(up_rev_tree2),
                added=["debian/", "debian/changelog"])
        self.check_changes(rev_tree2.changes_from(rev_tree1),
                modified=["README", "debian/changelog"])
        self.check_changes(up_rev_tree2.changes_from(up_rev_tree1),
                modified=["README"])


class SourcePackageBuilder(object):

    def __init__(self, name, version):
        self.upstream_files = []
        self.debian_files = []
        self.name = name
        self.version = version

    def add_upstream_file(self, name, content=None):
        self.add_upstream_files([(name, content)])

    def add_upstream_files(self, files):
        self.upstream_files += files

    def add_debian_file(self, name, content=None):
        self.add_debian_files([(name, content)])

    def add_debian_files(self, files):
        self.debian_files += files

    def orig_name(self):
        v_num = str(self.version.upstream_version)
        return "%s_%s.orig.tar.gz" % (self.name, v_num)

    def diff_name(self):
        return "%s_%s.diff.gz" % (self.name, str(self.version))

    def dsc_name(self):
        return "%s_%s.dsc" % (self.name, str(self.version))

    def _make_files(self, files_list, basedir):
        for (path, content) in files_list:
            dirname = os.path.dirname(path)
            if dirname is not None and dirname != "":
                os.makedirs(os.path.join(basedir, dirname))
            f = open(os.path.join(basedir, path), 'wb')
            try:
                if content is None:
                    content = ''
                f.write(content)
            finally:
                f.close()

    def basedir(self):
        return self.name + "-" + str(self.version.upstream_version)

    def _make_base(self):
        basedir = self.basedir()
        os.mkdir(basedir)
        self._make_files(self.upstream_files, basedir)
        return basedir

    def build_orig(self):
        basedir = self._make_base()
        tar = tarfile.open(self.orig_name(), 'w:gz')
        try:
          tar.add(basedir)
        finally:
          tar.close()
        shutil.rmtree(basedir)

    def build(self):
        self.build_orig()
        basedir = self._make_base()
        orig_basedir = basedir + ".orig"
        shutil.copytree(basedir, orig_basedir)
        self._make_files(self.debian_files, basedir)
        os.system('diff -Nru %s %s | gzip -9 - > %s' % (orig_basedir,
                    basedir, self.diff_name()))
        shutil.rmtree(basedir)
        shutil.rmtree(orig_basedir)
        f = open(self.dsc_name(), 'wb')
        try:
            f.write("""Format: 1.0
Source: %s
Version: %s
Binary: package
Maintainer: maintainer <maint@maint.org>
Architecture: any
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 5.0.0)
Files:
 8636a3e8ae81664bac70158503aaf53a 1328218 %s
 1acd97ad70445afd5f2a64858296f211 20709   %s
""" % (self.name, self.version, self.orig_name(), self.diff_name()))
        finally:
            f.close()

