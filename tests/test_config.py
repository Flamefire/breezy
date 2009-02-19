#    test_config.py -- Tests for builddeb's config.py
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

from debian_bundle.changelog import Version

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.builddeb.config import DebBuildConfig


class DebBuildConfigTests(TestCaseWithTransport):

  def setUp(self):
    super(DebBuildConfigTests, self).setUp()
    self.tree = self.make_branch_and_tree('.')
    self.branch = self.tree.branch
    f = open('default.conf', 'wb')
    try:
      f.write('['+DebBuildConfig.section+']\n')
      f.write('builder = invalid builder\n') # shouldn't be read as it needs
                                             # to be trusted
      f.write('build-dir = default build dir\n')
      f.write('orig-dir = default orig dir\n')
      f.write('result-dir = default result dir\n')
    finally:
      f.close()
    f = open('user.conf', 'wb')
    try:
      f.write('['+DebBuildConfig.section+']\n')
      f.write('builder = valid builder\n')
      f.write('quick-builder = valid quick builder\n')
      f.write('orig-dir = user orig dir\n')
      f.write('result-dir = user result dir\n')
    finally:
      f.close()
    f = open('.bzr/branch/branch.conf', 'wb')
    try:
      f.write('['+DebBuildConfig.section+']\n')
      f.write('quick-builder = invalid quick builder\n')
      f.write('result-dir = branch result dir\n')
    finally:
      f.close()
    self.tree.add(['default.conf', 'user.conf'])
    version = Version('0.1-1')
    self.config = DebBuildConfig([('user.conf', True),
                                  ('default.conf', False)], branch=self.branch,
                                 version=version)

  def test_secure_not_from_untrusted(self):
    self.assertEqual(self.config.builder, 'valid builder')

  def test_secure_not_from_branch(self):
    self.assertEqual(self.config.quick_builder, 'valid quick builder')

  def test_branch_over_all(self):
    self.assertEqual(self.config.result_dir, 'branch result dir')

  def test_hierarchy(self):
    self.assertEqual(self.config.orig_dir, 'user orig dir')
    self.assertEqual(self.config.build_dir, 'default build dir')

  def test_no_entry(self):
    self.assertEqual(self.config.merge, False)

try:
  from bzrlib.plugins.svn.config import SubversionBuildPackageConfig
except ImportError:
  pass
else:
  from bzrlib.plugins.svn.tests import SubversionTestCase

  class DebuildSvnBpTests(SubversionTestCase):

    def test_from_properties(self):
      repos_url = self.make_repository("d")

      cfg = DebBuildConfig([], tree=Branch.open(repos_url).basis_tree())
      self.assertEquals(False, cfg.merge)

      dc = self.get_commit_editor(repos_url)
      d = dc.add_dir("debian")
      d.change_prop("mergeWithUpstream", "1")
      d.change_prop("svn-bp:origDir", "someorigdir")
      dc.close()

      cfg = DebBuildConfig([], tree=Branch.open(repos_url).basis_tree())
      self.assertEquals(True, cfg.merge)
      self.assertEquals("someorigdir", cfg.orig_dir)

    def test_from_svn_layout_file(self):
      repos_url = self.make_repository("d")

      cfg = DebBuildConfig([], tree=Branch.open(repos_url).basis_tree())
      self.assertEquals(False, cfg.merge)

      dc = self.get_commit_editor(repos_url)
      d = dc.add_dir("debian")
      f = d.add_file("debian/svn-layout")
      f.modify("origDir = someorigdir\n")
      dc.close()

      cfg = DebBuildConfig([], tree=Branch.open(repos_url).basis_tree())
      self.assertEquals("someorigdir", cfg.orig_dir)

# vim: ts=2 sts=2 sw=2
