# Copyright (C) 2008, 2009 Canonical Ltd
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

import os
import stat
import sys


from bzrlib import (
    branch,
    bzrdir,
    config,
    errors,
    osutils,
    remote,
    revisionspec,
    tests,
    transport,
    workingtree,
    uncommit,
    )
from bzrlib.smart import server as smart_server
from bzrlib.tests import (
    per_branch,
    per_transport,
    )
from bzrlib.transport import (
    ftp,
    sftp,
    )
from bzrlib.plugins import upload


def get_transport_scenarios():
    result = []
    basis = per_transport.transport_test_permutations()
    # Keep only the interesting ones for upload
    for name, d in basis:
        t_class = d['transport_class']
        if t_class in (ftp.FtpTransport, sftp.SFTPTransport):
            result.append((name, d))
    try:
        import bzrlib.plugins.local_test_server
        from bzrlib.plugins.local_test_server import test_server
        if False:
            # XXX: Disable since we can't get chmod working for anonymous
            # user
            scenario = ('vsftpd',
                        {'transport_class': test_server.FtpTransport,
                         'transport_server': test_server.Vsftpd,
                         })
            result.append(scenario)
        from test_server import ProftpdFeature
        if ProftpdFeature().available():
            scenario = ('proftpd',
                        {'transport_class': test_server.FtpTransport,
                         'transport_server': test_server.Proftpd,
                         })
            result.append(scenario)
        # XXX: add support for pyftpdlib
    except ImportError:
        pass
    return result


def load_tests(standard_tests, module, loader):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()

    # one for each transport implementation
    t_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance((
                TestFullUpload,
                TestIncrementalUpload,
                TestUploadFromRemoteBranch,
                )))
    tests.multiply_tests(t_tests, get_transport_scenarios(), result)

    # one for each branch format
    b_tests, remaining_tests = tests.split_suite_by_condition(
        remaining_tests, tests.condition_isinstance((
                TestBranchUploadLocations,
                )))
    tests.multiply_tests(b_tests, per_branch.branch_scenarios(),
                         result)

    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class UploadUtilsMixin(object):
    """Helper class to write upload tests.

    This class provides helpers to simplify test writing. The emphasis is on
    easy test writing, so each tree modification is committed. This doesn't
    preclude writing tests spawning several revisions to upload more complex
    changes.
    """

    upload_dir = 'upload'
    branch_dir = 'branch'

    def make_branch_and_working_tree(self):
        t = transport.get_transport(self.branch_dir)
        t.ensure_base()
        branch = bzrdir.BzrDir.create_branch_convenience(
            t.base,
            format=bzrdir.format_registry.make_bzrdir('default'),
            force_new_tree=False)
        self.tree = branch.bzrdir.create_workingtree()
        self.tree.commit('initial empty tree')

    def assertUpFileEqual(self, content, path, base=upload_dir):
        self.assertFileEqual(content, osutils.pathjoin(base, path))

    def assertUpPathModeEqual(self, path, expected_mode, base=upload_dir):
        # FIXME: the tests needing that assertion should depend on the server
        # ability to handle chmod so that they don't fail (or be skipped)
        # against servers that can't. Note that some bzrlib transports define
        # _can_roundtrip_unix_modebits in a incomplete way, this property
        # should depend on both the client and the server, not the client only.
        # But the client will know or can find if the server support chmod so
        # that's the client that will report it anyway.
        full_path = osutils.pathjoin(base, path)
        st = os.stat(full_path)
        mode = st.st_mode & 0777
        if expected_mode == mode:
            return
        raise AssertionError(
            'For path %s, mode is %s not %s' %
            (full_path, oct(mode), oct(expected_mode)))

    def failIfUpFileExists(self, path, base=upload_dir):
        self.failIfExists(osutils.pathjoin(base, path))

    def failUnlessUpFileExists(self, path, base=upload_dir):
        self.failUnlessExists(osutils.pathjoin(base, path))

    def set_file_content(self, path, content, base=branch_dir):
        f = file(osutils.pathjoin(base, path), 'wb')
        try:
            f.write(content)
        finally:
            f.close()

    def add_file(self, path, content, base=branch_dir):
        self.set_file_content(path, content, base)
        self.tree.add(path)
        self.tree.commit('add file %s' % path)

    def modify_file(self, path, content, base=branch_dir):
        self.set_file_content(path, content, base)
        self.tree.commit('modify file %s' % path)

    def chmod_file(self, path, mode, base=branch_dir):
        full_path = osutils.pathjoin(base, path)
        os.chmod(full_path, mode)
        self.tree.commit('change file %s mode to %s' % (path, oct(mode)))

    def delete_any(self, path, base=branch_dir):
        self.tree.remove([path], keep_files=False)
        self.tree.commit('delete %s' % path)

    def add_dir(self, path, base=branch_dir):
        os.mkdir(osutils.pathjoin(base, path))
        self.tree.add(path)
        self.tree.commit('add directory %s' % path)

    def rename_any(self, old_path, new_path):
        self.tree.rename_one(old_path, new_path)
        self.tree.commit('rename %s into %s' % (old_path, new_path))

    def transform_dir_into_file(self, path, content, base=branch_dir):
        osutils.delete_any(osutils.pathjoin(base, path))
        self.set_file_content(path, content, base)
        self.tree.commit('change %s from dir to file' % path)

    def transform_file_into_dir(self, path, base=branch_dir):
        # bzr can't handle that kind change in a single commit without an
        # intervening bzr status (see bug #205636).
        self.tree.remove([path], keep_files=False)
        os.mkdir(osutils.pathjoin(base, path))
        self.tree.add(path)
        self.tree.commit('change %s from file to dir' % path)

    def _get_cmd_upload(self):
        cmd = upload.cmd_upload()
        # We don't want to use run_bzr here because redirected output are a
        # pain to debug. But we need to provides a valid outf.
        # XXX: Should a bug against bzr be filled about that ?
        cmd._setup_outf()
        return cmd

    def do_full_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_url(self.upload_dir)
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = self.branch_dir
        kwargs['full'] = True
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)

    def do_incremental_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_url(self.upload_dir)
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = self.branch_dir
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)


class TestUploadMixin(UploadUtilsMixin):
    """Helper class to share tests between full and incremental uploads."""

    def test_create_file(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file('hello', 'foo')

        self.do_upload()

        self.assertUpFileEqual('foo', 'hello')

    def test_create_file_in_subdir(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_dir('dir')
        self.add_file('dir/goodbye', 'baz')

        self.failIfUpFileExists('dir/goodbye')

        self.do_upload()

        self.assertUpFileEqual('baz', 'dir/goodbye')
        self.assertUpPathModeEqual('dir', 0775)

    def test_modify_file(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.modify_file('hello', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')

    def test_rename_one_file(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.rename_any('hello', 'goodbye')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('foo', 'goodbye')

    def test_rename_and_change_file(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.rename_any('hello', 'goodbye')
        self.modify_file('goodbye', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'goodbye')

    def test_rename_two_files(self):
        self.make_branch_and_working_tree()
        self.add_file('a', 'foo')
        self.add_file('b', 'qux')
        self.do_full_upload()
        # We rely on the assumption that bzr will topologically sort the
        # renames which will cause a -> b to appear *before* b -> c
        self.rename_any('b', 'c')
        self.rename_any('a', 'b')

        self.assertUpFileEqual('foo', 'a')
        self.assertUpFileEqual('qux', 'b')

        self.do_upload()

        self.assertUpFileEqual('foo', 'b')
        self.assertUpFileEqual('qux', 'c')

    def test_upload_revision(self):
        self.make_branch_and_working_tree() # rev1
        self.do_full_upload()
        self.add_file('hello', 'foo') # rev2
        self.modify_file('hello', 'bar') # rev3

        self.failIfUpFileExists('hello')

        revspec = revisionspec.RevisionSpec.from_string('2')
        self.do_upload(revision=[revspec])

        self.assertUpFileEqual('foo', 'hello')

    def test_no_upload_when_changes(self):
        self.make_branch_and_working_tree()
        self.add_file('a', 'foo')
        self.set_file_content('a', 'bar')

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def test_no_upload_when_conflicts(self):
        self.make_branch_and_working_tree()
        self.add_file('a', 'foo')
        self.run_bzr('branch branch other')
        self.modify_file('a', 'bar')
        other_tree = workingtree.WorkingTree.open('other')
        self.set_file_content('a', 'baz', 'other/')
        other_tree.commit('modify file a')

        self.run_bzr('merge -d branch other', retcode=1)

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def test_change_file_into_dir(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.transform_file_into_dir('hello')
        self.add_file('hello/file', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello/file')

    def test_change_dir_into_file(self):
        self.make_branch_and_working_tree()
        self.add_dir('hello')
        self.add_file('hello/file', 'foo')
        self.do_full_upload()
        self.delete_any('hello/file')
        self.transform_dir_into_file('hello', 'bar')

        self.assertUpFileEqual('foo', 'hello/file')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')

    def test_make_file_executable(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.chmod_file('hello', 0664)
        self.do_full_upload()
        self.chmod_file('hello', 0755)

        self.assertUpPathModeEqual('hello', 0664)

        self.do_upload()

        self.assertUpPathModeEqual('hello', 0775)

    def get_upload_auto(self):
        return upload.get_upload_auto(self.tree.branch)

    def test_upload_auto(self):
        """Test that upload --auto sets the upload_auto option"""
        self.make_branch_and_working_tree()

        self.add_file('hello', 'foo')
        self.assertFalse(self.get_upload_auto())
        self.do_full_upload(auto=True)
        self.assertUpFileEqual('foo', 'hello')
        self.assertTrue(self.get_upload_auto())

        # and check that it stays set until it is unset
        self.add_file('bye', 'bar')
        self.do_full_upload()
        self.assertUpFileEqual('bar', 'bye')
        self.assertTrue(self.get_upload_auto())

    def test_upload_noauto(self):
        """Test that upload --no-auto unsets the upload_auto option"""
        self.make_branch_and_working_tree()

        self.add_file('hello', 'foo')
        self.do_full_upload(auto=True)
        self.assertUpFileEqual('foo', 'hello')
        self.assertTrue(self.get_upload_auto())

        self.add_file('bye', 'bar')
        self.do_full_upload(auto=False)
        self.assertUpFileEqual('bar', 'bye')
        self.assertFalse(self.get_upload_auto())

        # and check that it stays unset until it is set
        self.add_file('again', 'baz')
        self.do_full_upload()
        self.assertUpFileEqual('baz', 'again')
        self.assertFalse(self.get_upload_auto())

    def test_upload_from_subdir(self):
        self.make_branch_and_working_tree()
        self.build_tree(['branch/foo/', 'branch/foo/bar'])
        self.tree.add(['foo/', 'foo/bar'])
        self.tree.commit("Add directory")
        self.do_full_upload(directory='branch/foo')

    def test_upload_revid_path_in_dir(self):
        self.make_branch_and_working_tree()
        self.add_dir('dir')
        self.add_file('dir/goodbye', 'baz')

        revid_path = 'dir/revid-path'
        upload.set_upload_revid_location(self.tree.branch, revid_path)
        self.failIfUpFileExists(revid_path)

        self.do_full_upload()

        self.add_file('dir/hello', 'foo')

        self.do_upload()

        self.failUnlessUpFileExists(revid_path)
        self.assertUpFileEqual('baz', 'dir/goodbye')
        self.assertUpFileEqual('foo', 'dir/hello')

    def test_ignore_file(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file('.bzrignore-upload','foo')
        self.add_file('foo', 'bar')

        self.do_upload()

        self.failIfUpFileExists('foo')

    def test_ignore_directory(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file('.bzrignore-upload','dir')
        self.add_dir('dir')

        self.do_upload()

        self.failIfUpFileExists('dir')

    def test_ignore_nested_directory(self):
        self.make_branch_and_working_tree()
        self.do_full_upload()
        self.add_file('.bzrignore-upload','dir')
        self.add_dir('dir')
        self.add_dir('dir/foo')
        self.add_file('dir/foo/bar','')

        self.do_upload()

        self.failIfUpFileExists('dir')
        self.failIfUpFileExists('dir/foo/bar')


class TestFullUpload(tests.TestCaseWithTransport, TestUploadMixin):

    do_upload = TestUploadMixin.do_full_upload

    def test_full_upload_empty_tree(self):
        self.make_branch_and_working_tree()

        self.do_full_upload()

        revid_path = upload.get_upload_revid_location(self.tree.branch)
        self.failUnlessUpFileExists(revid_path)

    def test_invalid_revspec(self):
        self.make_branch_and_working_tree()
        rev1 = revisionspec.RevisionSpec.from_string('1')
        rev2 = revisionspec.RevisionSpec.from_string('2')

        self.assertRaises(errors.BzrCommandError,
                          self.do_incremental_upload, revision=[rev1, rev2])

    def test_create_remote_dir_twice(self):
        self.make_branch_and_working_tree()
        self.add_dir('dir')
        self.do_full_upload()
        self.add_file('dir/goodbye', 'baz')

        self.failIfUpFileExists('dir/goodbye')

        self.do_full_upload()

        self.assertUpFileEqual('baz', 'dir/goodbye')
        self.assertUpPathModeEqual('dir', 0775)


class TestIncrementalUpload(tests.TestCaseWithTransport, TestUploadMixin):

    do_upload = TestUploadMixin.do_incremental_upload

    # XXX: full upload doesn't handle deletions....

    def test_delete_one_file(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.delete_any('hello')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.failIfUpFileExists('hello')

    def test_delete_dir_and_subdir(self):
        self.make_branch_and_working_tree()
        self.add_dir('dir')
        self.add_dir('dir/subdir')
        self.add_file('dir/subdir/a', 'foo')
        self.do_full_upload()
        self.rename_any('dir/subdir/a', 'a')
        self.delete_any('dir/subdir')
        self.delete_any('dir')

        self.assertUpFileEqual('foo', 'dir/subdir/a')

        self.do_upload()

        self.failIfUpFileExists('dir/subdir/a')
        self.failIfUpFileExists('dir/subdir')
        self.failIfUpFileExists('dir')
        self.assertUpFileEqual('foo', 'a')

    def test_delete_one_file_rename_to_deleted(self):
        self.make_branch_and_working_tree()
        self.add_file('a', 'foo')
        self.add_file('b', 'bar')
        self.do_full_upload()
        self.delete_any('a')
        self.rename_any('b', 'a')

        self.assertUpFileEqual('foo', 'a')

        self.do_upload()

        self.failIfUpFileExists('b')
        self.assertUpFileEqual('bar', 'a')

    def test_rename_outside_dir_delete_dir(self):
        self.make_branch_and_working_tree()
        self.add_dir('dir')
        self.add_file('dir/a', 'foo')
        self.do_full_upload()
        self.rename_any('dir/a', 'a')
        self.delete_any('dir')

        self.assertUpFileEqual('foo', 'dir/a')

        self.do_upload()

        self.failIfUpFileExists('dir/a')
        self.failIfUpFileExists('dir')
        self.assertUpFileEqual('foo', 'a')

    def test_upload_for_the_first_time_do_a_full_upload(self):
        self.make_branch_and_working_tree()
        self.add_file('hello', 'bar')

        revid_path = upload.get_upload_revid_location(self.tree.branch)
        self.failIfUpFileExists(revid_path)

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')


class TestBranchUploadLocations(per_branch.TestCaseWithBranch):

    def test_get_upload_location_unset(self):
        config = self.get_branch().get_config()
        self.assertEqual(None, config.get_user_option('upload_location'))

    def test_get_push_location_exact(self):
        config.ensure_config_dir_exists()
        fn = config.locations_config_filename()
        b = self.get_branch()
        open(fn, 'wt').write(("[%s]\n"
                                  "upload_location=foo\n" %
                                  b.base[:-1]))
        conf = b.get_config()
        self.assertEqual("foo", conf.get_user_option('upload_location'))

    def test_set_push_location(self):
        conf = self.get_branch().get_config()
        conf.set_user_option('upload_location', 'foo')
        self.assertEqual('foo', conf.get_user_option('upload_location'))


class TestUploadFromRemoteBranch(tests.TestCaseWithTransport,
                                 UploadUtilsMixin):

    remote_branch_dir = 'remote_branch'

    def setUp(self):
        super(TestUploadFromRemoteBranch, self).setUp()
        self.remote_branch_url = self.make_remote_branch_without_working_tree()

    def make_remote_branch_without_working_tree(self):
        """Creates a branch without working tree to upload from.

        It's created from the existing self.branch_dir one which still has its
        working tree.
        """
        self.make_branch_and_working_tree()
        self.add_file('hello', 'foo')

        remote_branch_url = self.get_url(self.remote_branch_dir)
        if self.transport_server is sftp.SFTPHomeDirServer:
            # FIXME: Some policy search ends up above the user home directory
            # and are seen as attemps to escape test isolation
            raise tests.TestNotApplicable('Escaping test isolation')
        self.run_bzr(['push', remote_branch_url,
                      '--directory', self.branch_dir])
        return remote_branch_url

    def test_no_upload_to_remote_working_tree(self):
        cmd = self._get_cmd_upload()
        up_url = self.get_url(self.branch_dir)
        # Let's try to upload from the just created remote branch into the
        # branch (which has a working tree).
        self.assertRaises(upload.CannotUploadToWorkingTree,
                          cmd.run, up_url, directory=self.remote_branch_url)

    def test_upload_without_working_tree(self):
        self.do_full_upload(directory=self.remote_branch_url)
        self.assertUpFileEqual('foo', 'hello')


class TestUploadDiverged(tests.TestCaseWithTransport,
                         UploadUtilsMixin):

    def setUp(self):
        super(TestUploadDiverged, self).setUp()
        self.diverged_tree = self.make_diverged_tree_and_upload_location()

    def make_diverged_tree_and_upload_location(self):
        tree_a = self.make_branch_and_tree('tree_a')
        tree_a.commit('message 1', rev_id='rev1')
        tree_a.commit('message 2', rev_id='rev2a')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        uncommit.uncommit(tree_b.branch, tree=tree_b)
        tree_b.commit('message 2', rev_id='rev2b')
        # upload tree a
        self.do_full_upload(directory=tree_a.basedir)
        return tree_b

    def assertRevidUploaded(self, revid):
        t = self.get_transport(self.upload_dir)
        uploaded_revid = t.get_bytes('.bzr-upload.revid')
        self.assertEqual(revid, uploaded_revid)

    def test_cant_upload_diverged(self):
        self.assertRaises(upload.DivergedUploadedTree,
                          self.do_incremental_upload,
                          directory=self.diverged_tree.basedir)
        self.assertRevidUploaded('rev2a')

    def test_upload_diverged_with_overwrite(self):
        self.do_incremental_upload(directory=self.diverged_tree.basedir,
                                   overwrite=True)
        self.assertRevidUploaded('rev2b')
