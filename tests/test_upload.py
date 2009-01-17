# Copyright (C) 2008 Canonical Ltd
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
    builtins,
    bzrdir,
    errors,
    osutils,
    remote,
    revisionspec,
    tests,
    transport,
    workingtree,
    )
from bzrlib.smart import server as smart_server

from bzrlib.tests import (
    test_transport_implementations,
    branch_implementations,
    )


from bzrlib.plugins.upload import (
    cmd_upload,
    BzrUploader,
    get_upload_auto,
    CannotUploadToWT,
    )


class TransportAdapter(
    test_transport_implementations.TransportTestProviderAdapter):
    """A tool to generate a suite testing all transports for a single test.

    We restrict the transports to the ones we want to support.
    """

    def _test_permutations(self):
        """Return a list of the klass, server_factory pairs to test."""
        result = []
        transport_modules =['bzrlib.transport.ftp',
                            'bzrlib.transport.sftp']
        for module in transport_modules:
            try:
                permutations = self.get_transport_test_permutations(
                    reduce(getattr, (module).split('.')[1:],
                           __import__(module)))
                for (klass, server_factory) in permutations:
                    scenario = (server_factory.__name__,
                        {"transport_class":klass,
                         "transport_server":server_factory})
                    result.append(scenario)
            except errors.DependencyNotPresent, e:
                # Continue even if a dependency prevents us 
                # from adding this test
                pass
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
            if test_server.ProftpdFeature().available():
                scenario = ('proftpd',
                            {'transport_class': test_server.FtpTransport,
                             'transport_server': test_server.Proftpd,
                             })
                result.append(scenario)
        except ImportError:
            pass
        return result


def load_tests(standard_tests, module, loader):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()

    is_testing_for_transports = tests.condition_isinstance(
        (TestFullUpload,
         TestIncrementalUpload,
         TestFullUploadFromRemote,
         TestIncrementalUploadFromRemote))
    transport_adapter = TransportAdapter()

    is_testing_for_branches = tests.condition_isinstance(
        (TestBranchUploadLocations,))
    # Generate a list of branch formats and their associated bzrdir formats to
    # use.
    # XXX: This was copied from bzrlib.tests.branch_implementations.tests_suite
    # and need to be shared in a better way.
    combinations = [(format, format._matchingbzrdir) for format in
         branch.BranchFormat._formats.values() + branch._legacy_formats]
    BTPA = branch_implementations.BranchTestProviderAdapter
    branch_adapter = BTPA(
        # None here will cause the default vfs transport server to be used.
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        combinations)
    branch_adapter_for_ss = BTPA(
        smart_server.SmartTCPServer_for_testing,
        smart_server.ReadonlySmartTCPServer_for_testing,
        [(remote.RemoteBranchFormat(), remote.RemoteBzrDirFormat())],
        # XXX: Report to bzr list, this parameter is not used in the
        # constructor

        # MemoryServer
        )

    for test_class in tests.iter_suite_tests(standard_tests):
        # Each test class is either standalone or testing for some combination
        # of transport or branch. Use the right adpater (or none) depending on
        # the class.
        if is_testing_for_transports(test_class):
            result.addTests(transport_adapter.adapt(test_class))
        elif is_testing_for_branches(test_class):
            result.addTests(branch_adapter.adapt(test_class))
            result.addTests(branch_adapter_for_ss.adapt(test_class))
        else:
            result.addTest(test_class)
    return result


class TestUploadMixin(object):
    """Helper class to share tests between full and incremental uploads.

    This class also provides helpers to simplify test writing. The emphasis is
    on easy test writing, so each tree modification is committed. This doesn't
    preclude writing tests spawning several revisions to upload more complex
    changes.
    """

    upload_dir = 'upload/'
    branch_dir = 'branch/'

    def make_local_branch(self):
        t = transport.get_transport('branch')
        t.ensure_base()
        branch = bzrdir.BzrDir.create_branch_convenience(
            t.base,
            format=bzrdir.format_registry.make_bzrdir('default'),
            force_new_tree=False)
        self.tree = branch.bzrdir.create_workingtree()
        self.tree.commit('initial empty tree')

    def assertUpFileEqual(self, content, path, base=upload_dir):
        self.assertFileEqual(content, base + path)

    def assertUpPathModeEqual(self, path, expected_mode, base=upload_dir):
        # FIXME: the tests needing that assertion should depend on the server
        # ability to handle chmod so that they don't fail (or be skipped)
        # against servers that can't. Note that some bzrlib transports define
        # _can_roundtrip_unix_modebits in a incomplete way, this property
        # should depend on both the client and the server, not the client only.
        st = os.stat(base + path)
        mode = st.st_mode & 0777
        if expected_mode == mode:
            return
        raise AssertionError(
            'For path %s, mode is %s not %s' %
            (base + path, oct(mode), oct(expected_mode)))

    def failIfUpFileExists(self, path, base=upload_dir):
        self.failIfExists(base + path)

    def failUnlessUpFileExists(self, path, base=upload_dir):
        self.failUnlessExists(base + path)

    def set_file_content(self, name, content, base=branch_dir):
        f = file(base + name, 'wb')
        try:
            f.write(content)
        finally:
            f.close()

    def add_file(self, name, content, base=branch_dir):
        self.set_file_content(name, content, base)
        self.tree.add(name)
        self.tree.commit('add file %s' % name)

    def modify_file(self, name, content, base=branch_dir):
        self.set_file_content(name, content, base)
        self.tree.commit('modify file %s' % name)

    def chmod_file(self, name, mode, base=branch_dir):
        path = base + name
        os.chmod(path, mode)
        self.tree.commit('change file %s mode to %s' % (name, oct(mode)))

    def delete_any(self, name, base=branch_dir):
        self.tree.remove([name], keep_files=False)
        self.tree.commit('delete %s' % name)

    def add_dir(self, name, base=branch_dir):
        os.mkdir(base + name)
        self.tree.add(name)
        self.tree.commit('add directory %s' % name)

    def rename_any(self, old_name, new_name):
        self.tree.rename_one(old_name, new_name)
        self.tree.commit('rename %s into %s' % (old_name, new_name))

    def transform_dir_into_file(self, name, content, base=branch_dir):
        osutils.delete_any(base + name)
        self.set_file_content(name, content, base)
        self.tree.commit('change %s from dir to file' % name)

    def transform_file_into_dir(self, name, base=branch_dir):
        # bzr can't handle that kind change in a single commit without an
        # intervening bzr status (see bug #205636).
        self.tree.remove([name], keep_files=False)
        os.mkdir(base + name)
        self.tree.add(name)
        self.tree.commit('change %s from file to dir' % name)

    def _get_cmd_upload(self):
        upload = cmd_upload()
        # We don't want to use run_bzr here because redirected output are a
        # pain to debug. But we need to provides a valid outf.
        # XXX: Should a bug against bzr be filled about that ?
        upload._setup_outf()
        return upload

    def do_full_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_transport(self.upload_dir).external_url()
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = 'branch'
        kwargs['full'] = True
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)

    def do_incremental_upload(self, *args, **kwargs):
        upload = self._get_cmd_upload()
        up_url = self.get_transport(self.upload_dir).external_url()
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = 'branch'
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)

    def test_create_file(self):
        self.make_local_branch()
        self.do_full_upload()
        self.add_file('hello', 'foo')

        self.do_upload()

        self.assertUpFileEqual('foo', 'hello')

    def test_create_file_in_subdir(self):
        self.make_local_branch()
        self.do_full_upload()
        self.add_dir('dir')
        self.add_file('dir/goodbye', 'baz')

        self.failIfUpFileExists('dir/goodbye')

        self.do_upload()

        self.assertUpFileEqual('baz', 'dir/goodbye')
        self.assertUpPathModeEqual('dir', 0775)

    def test_modify_file(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.modify_file('hello', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')

    def test_rename_one_file(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.rename_any('hello', 'goodbye')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('foo', 'goodbye')

    def test_rename_and_change_file(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.rename_any('hello', 'goodbye')
        self.modify_file('goodbye', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'goodbye')

    def test_rename_two_files(self):
        self.make_local_branch()
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
        self.make_local_branch() # rev1
        self.do_full_upload()
        self.add_file('hello', 'foo') # rev2
        self.modify_file('hello', 'bar') # rev3

        self.failIfUpFileExists('hello')

        revspec = revisionspec.RevisionSpec.from_string('2')
        self.do_upload(revision=[revspec])

        self.assertUpFileEqual('foo', 'hello')

    def test_no_upload_when_changes(self):
        self.make_local_branch()
        self.add_file('a', 'foo')
        self.set_file_content('a', 'bar')

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def test_no_upload_when_conflicts(self):
        self.make_local_branch()
        self.add_file('a', 'foo')
        self.run_bzr('branch branch other')
        self.modify_file('a', 'bar')
        other_tree = workingtree.WorkingTree.open('other')
        self.set_file_content('a', 'baz', 'other/')
        other_tree.commit('modify file a')

        self.run_bzr('merge -d branch other', retcode=1)

        self.assertRaises(errors.UncommittedChanges, self.do_upload)

    def test_change_file_into_dir(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.transform_file_into_dir('hello')
        self.add_file('hello/file', 'bar')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello/file')

    def test_change_dir_into_file(self):
        self.make_local_branch()
        self.add_dir('hello')
        self.add_file('hello/file', 'foo')
        self.do_full_upload()
        self.delete_any('hello/file')
        self.transform_dir_into_file('hello', 'bar')

        self.assertUpFileEqual('foo', 'hello/file')

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')

    def test_make_file_executable(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.chmod_file('hello', 0664)
        self.do_full_upload()
        self.chmod_file('hello', 0755)

        self.assertUpPathModeEqual('hello', 0664)

        self.do_upload()

        self.assertUpPathModeEqual('hello', 0775)

    def get_upload_auto(self):
        return get_upload_auto(self.tree.branch)

    def test_upload_auto(self):
        """Test that upload --auto sets the upload_auto option"""
        self.make_local_branch()

        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.assertUpFileEqual('foo', 'hello')
        self.assertFalse(self.get_upload_auto())

        self.add_file('bye', 'bar')
        self.do_full_upload(auto=True)
        self.assertUpFileEqual('bar', 'bye')
        self.assertTrue(self.get_upload_auto())

        # and check that it stays set until it is unset
        self.add_file('again', 'baz')
        self.do_full_upload()
        self.assertUpFileEqual('baz', 'again')
        self.assertTrue(self.get_upload_auto())

    def test_upload_noauto(self):
        """Test that upload --no-auto unsets the upload_auto option"""
        self.make_local_branch()

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
        self.make_local_branch()
        self.build_tree(['branch/foo/', 'branch/foo/bar'])
        self.tree.add(['foo/', 'foo/bar'])
        self.tree.commit("Add directory")
        self.do_full_upload(directory='branch/foo')

    def test_no_upload_remote_wt(self):
        self.make_local_branch()
        self.add_file('hello', 'foo')

        #Create branch in remote tree to create wt
        t = transport.get_transport(self.upload_dir)
        self.branch = bzrdir.BzrDir.create_branch_convenience(
            t.base,
            format=bzrdir.format_registry.make_bzrdir('default'),
            force_new_tree=True)

        self.assertRaises(CannotUploadToWT, self.do_upload)


class TestFullUpload(tests.TestCaseWithTransport, TestUploadMixin):

    do_upload = TestUploadMixin.do_full_upload

    def test_full_upload_empty_tree(self):
        self.make_local_branch()

        self.do_full_upload()

        self.failUnlessUpFileExists(BzrUploader.bzr_upload_revid_file_name)

    def test_invalid_revspec(self):
        self.make_local_branch()
        rev1 = revisionspec.RevisionSpec.from_string('1')
        rev2 = revisionspec.RevisionSpec.from_string('2')

        self.assertRaises(errors.BzrCommandError,
                          self.do_incremental_upload, revision=[rev1, rev2])

    def test_create_remote_dir_twice(self):
        self.make_local_branch()
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
        self.make_local_branch()
        self.add_file('hello', 'foo')
        self.do_full_upload()
        self.delete_any('hello')

        self.assertUpFileEqual('foo', 'hello')

        self.do_upload()

        self.failIfUpFileExists('hello')

    def test_delete_dir_and_subdir(self):
        self.make_local_branch()
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
        self.make_local_branch()
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
        self.make_local_branch()
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
        self.make_local_branch()
        self.add_file('hello', 'bar')

        self.failIfUpFileExists(BzrUploader.bzr_upload_revid_file_name)

        self.do_upload()

        self.assertUpFileEqual('bar', 'hello')

class TestUploadFromRemote(TestUploadMixin):

    def do_full_upload(self, *args, **kwargs):
        up_url = self.get_transport(self.upload_dir).external_url()

        push = builtins.cmd_push()
        push._setup_outf()
        push.run(location=up_url, directory='branch')

        upload = self._get_cmd_upload()
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = up_url
        kwargs['full'] = True
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)

    def do_incremental_upload(self, *args, **kwargs):
        up_url = self.get_transport(self.upload_dir).external_url()

        push = builtins.cmd_push()
        push._setup_outf()
        push.run(location=up_url, directory='branch')

        upload = self._get_cmd_upload()
        if kwargs.get('directory', None) is None:
            kwargs['directory'] = up_url
        kwargs['quiet'] = True
        upload.run(up_url, *args, **kwargs)

    def test_no_upload_when_changes(self):
        raise tests.TestNotApplicable()

    def test_no_upload_when_conflicts(self):
        raise tests.TestNotApplicable()

    remote_branch = None
    def get_upload_auto(self):
        if not self.remote_branch:
            self.remote_branch = branch.Branch.open_from_transport(\
                self.get_transport(self.upload_dir))

        return get_upload_auto(self.remote_branch)


class TestFullUploadFromRemote(tests.TestCaseWithTransport,
                               TestUploadFromRemote):

    do_upload = TestUploadFromRemote.do_full_upload


class TestIncrementalUploadFromRemote(tests.TestCaseWithTransport,
                                      TestUploadFromRemote):

    do_upload = TestUploadFromRemote.do_incremental_upload


class TestBranchUploadLocations(branch_implementations.TestCaseWithBranch):

    def test_get_upload_location_unset(self):
        config = self.get_branch().get_config()
        self.assertEqual(None, config.get_user_option('upload_location'))

    def test_get_push_location_exact(self):
        from bzrlib.config import (locations_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = locations_config_filename()
        b = self.get_branch()
        open(fn, 'wt').write(("[%s]\n"
                                  "upload_location=foo\n" %
                                  b.base[:-1]))
        config = b.get_config()
        self.assertEqual("foo", config.get_user_option('upload_location'))

    def test_set_push_location(self):
        config = self.get_branch().get_config()
        config.set_user_option('upload_location', 'foo')
        self.assertEqual('foo', config.get_user_option('upload_location'))

