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

"""Upload a working tree, incrementally.

Quickstart
----------

To get started, it's as simple as running::

    bzr upload sftp://user@host/location/on/webserver

This will initially upload the whole working tree, and leave a file on the
remote location indicating the last revision that was uploaded
(.bzr-upload.revid), in order to avoid uploading unnecessary information the
next time.

If you would like to upload a specific revision, you just do:

    bzr upload -r X  sftp://user@host/location/on/webserver

bzr-upload, just as bzr does, will remember the location where you upload the 
first time, so you don't need to specify it every time.

If you need to re-upload the whole working tree for some reason, you can:

    bzr upload --full sftp://user@host/location/on/webserver


Automatically Uploading
-----------------------

bzr-upload comes with a hook that can be used to trigger an upload whenever
the tip of the branch changes, including on commit, push, uncommit etc. This
would allow you to keep the code on the target up to date automatically.

The easiest way to enable this is to run upload with the --auto option.

     bzr upload --auto

will enable the hook for this branch. If you were to do a commit in this branch
now you would see it trigger the upload automatically.

If you wish to disable this for a branch again then you can use the --no-auto
option.

     bzr upload --no-auto

will disable the feature for that branch.

Since the auto hook is triggered automatically, you can't use the --quiet
option available for the upload command. Instead, you can set the
'upload_auto_quiet' configuration variable to True or False in either
bazaar.conf, locations.conf or branch.conf.


Storing the '.bzr-upload.revid' file
------------------------------------

The only bzr-related info uploaded with the working tree is the corresponding
revision id. The uploaded working tree is not linked to any other bzr data.

If the layout of your remote server is such that you can't write in the
root directory but only in the directories inside that root, you will need
to use the 'upload_revid_location' configuration variable to specify the
relative path to be used. That configuration variable can be specified in
locations.conf or branch.conf.

For example, given the following layout:

  Project/
    private/
    public/

you may have write access in 'private' and 'public' but in 'Project'
itself. In that case, you can add the following in your locations.conf or
branch.conf file:

  upload_revid_location = private/.bzr-upload.revid


Upload from Remote Location
---------------------------

It is possible to upload to a remote location from another remote location by
specifying it with the --directory option:

    bzr upload ftp://public.example.com --directory sftp://private.example.com 

This, together with --auto, can be used to upload when you push to your
central branch, rather than when you commit to your local branch.

Note that you will consume more bandwith this way than uploading from a local
branch.

Collaborating
-------------

While we don't have any platform setup, you can branch from trunk:

    bzr branch lp:bzr-upload

And change anything you'd like, and get in touch with any of the authors to 
review and add the changes.


Known Issues
------------

 * Symlinks are not supported


"""

# TODO: the chmod bits *can* be supported via the upload protocols
# (i.e. poorly), but since the web developers use these protocols to upload
# manually, it is expected that the associated web server is coherent with
# their presence/absence. In other words, if a web hosting provider requires
# chmod bits but don't provide an ftp server that support them, well, better
# find another provider ;-)

# TODO: The message emitted in verbose mode displays local paths. That may be
# scary for the user when we say 'Deleting <path>' and are referring to
# remote files...

from bzrlib import (
    branch,
    commands,
    lazy_import,
    option,
    )
lazy_import.lazy_import(globals(), """
import stat

from bzrlib import (
    bzrdir,
    errors,
    revisionspec,
    transport,
    osutils,
    urlutils,
    workingtree,
    )
""")

version_info = (1, 0, 0, 'dev', 0)
plugin_name = 'upload'


def _get_branch_option(branch, option):
    return branch.get_config().get_user_option(option)

# FIXME: Get rid of that as soon as we depend on a bzr API that includes
# get_user_option_as_bool
def _get_branch_bool_option(branch, option):
    conf = branch.get_config()
    if hasattr(conf, 'get_user_option_as_bool'):
        value = conf.get_user_option_as_bool(option)
    else:
        value = conf.get_user_option(option)
        if value is not None:
            if value.lower().strip() == 'true':
                value = True
            else:
                value = False
    return value

def _set_branch_option(branch, option, value):
    branch.get_config().set_user_option(option, value)


def get_upload_location(branch):
    return _get_branch_option(branch, 'upload_location')


def set_upload_location(branch, location):
    _set_branch_option(branch, 'upload_location', location)


# FIXME: Add more tests around invalid paths used here or relative paths that
# doesn't exist on remote (if only to get proper error messages)
def get_upload_revid_location(branch):
    loc =  _get_branch_option(branch, 'upload_revid_location')
    if loc is None:
        loc = '.bzr-upload.revid'
    return loc


def set_upload_revid_location(branch, location):
    _set_branch_option(branch, 'upload_revid_location', location)


def get_upload_auto(branch):
    auto = _get_branch_bool_option(branch, 'upload_auto')
    if auto is None:
        auto = False # Default to False if not specified
    return auto


def set_upload_auto(branch, auto):
    # FIXME: What's the point in allowing a boolean here instead of requiring
    # the callers to use strings instead ?
    if auto:
        auto_str = "True"
    else:
        auto_str = "False"
    _set_branch_option(branch, 'upload_auto', auto_str)


def get_upload_auto_quiet(branch):
    quiet = _get_branch_bool_option(branch, 'upload_auto_quiet')
    if quiet is None:
        quiet = False # Default to False if not specified
    return quiet


def set_upload_auto_quiet(branch, quiet):
    _set_branch_option(branch, 'upload_auto_quiet', quiet)


class BzrUploader(object):

    def __init__(self, branch, to_transport, outf, tree, rev_id,
                 quiet=False):
        self.branch = branch
        self.to_transport = to_transport
        self.outf = outf
        self.tree = tree
        self.rev_id = rev_id
        self.quiet = quiet
        self._pending_deletions = []
        self._pending_renames = []
        self._uploaded_revid = None

    def set_uploaded_revid(self, rev_id):
        # XXX: Add tests for concurrent updates, etc.
        revid_path = get_upload_revid_location(self.branch)
        self.to_transport.put_bytes(revid_path, rev_id)
        self._uploaded_revid = rev_id

    def get_uploaded_revid(self):
        if self._uploaded_revid is None:
            revid_path = get_upload_revid_location(self.branch)
            self._uploaded_revid = self.to_transport.get_bytes(revid_path)
        return self._uploaded_revid

    def upload_file(self, relpath, id, mode=None):
        if mode is None:
            if self.tree.is_executable(id):
                mode = 0775
            else:
                mode = 0664
        if not self.quiet:
            self.outf.write('Uploading %s\n' % relpath)
        self.to_transport.put_bytes(relpath, self.tree.get_file_text(id), mode)

    def upload_file_robustly(self, relpath, id, mode=None):
        """Upload a file, clearing the way on the remote side.

        When doing a full upload, it may happen that a directory exists where
        we want to put our file.
        """
        try:
            st = self.to_transport.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                # A simple rmdir may not be enough
                if not self.quiet:
                    self.outf.write('Clearing %s/%s\n' % (
                            self.to_transport.external_url(), relpath))
                self.to_transport.delete_tree(relpath)
        except errors.PathError:
            pass
        self.upload_file(relpath, id, mode)

    def make_remote_dir(self, relpath, mode=None):
        if mode is None:
            mode = 0775
        self.to_transport.mkdir(relpath, mode)

    def make_remote_dir_robustly(self, relpath, mode=None):
        """Create a remote directory, clearing the way on the remote side.

        When doing a full upload, it may happen that a file exists where we
        want to create our directory.
        """
        try:
            st = self.to_transport.stat(relpath)
            if not stat.S_ISDIR(st.st_mode):
                if not self.quiet:
                    self.outf.write('Deleting %s/%s\n' % (
                            self.to_transport.external_url(), relpath))
                self.to_transport.delete(relpath)
            else:
                # Ok the remote dir already exists, nothing to do
                return
        except errors.PathError:
            pass
        self.make_remote_dir(relpath, mode)

    def delete_remote_file(self, relpath):
        if not self.quiet:
            self.outf.write('Deleting %s\n' % relpath)
        self.to_transport.delete(relpath)

    def delete_remote_dir(self, relpath):
        if not self.quiet:
            self.outf.write('Deleting %s\n' % relpath)
        self.to_transport.rmdir(relpath)

    def delete_remote_dir_maybe(self, relpath):
        """Try to delete relpath, keeping failures to retry later."""
        try:
            self.to_transport.rmdir(relpath)
        # any kind of PathError would be OK, though we normally expect
        # DirectoryNotEmpty
        except errors.PathError:
            self._pending_deletions.append(relpath)

    def finish_deletions(self):
        if self._pending_deletions:
            # Process the previously failed deletions in reverse order to
            # delete children before parents
            for relpath in reversed(self._pending_deletions):
                self.to_transport.rmdir(relpath)
            # The following shouldn't be needed since we use it once per
            # upload, but better safe than sorry ;-)
            self._pending_deletions = []

    def rename_remote(self, old_relpath, new_relpath):
        """Rename a remote file or directory taking care of collisions.

        To avoid collisions during bulk renames, each renamed target is
        temporarily assigned a unique name. When all renames have been done,
        each target get its proper name.
        """
        # We generate a sufficiently random name to *assume* that
        # no collisions will occur and don't worry about it (nor
        # handle it).
        import os
        import random
        import time

        stamp = '.tmp.%.9f.%d.%d' % (time.time(),
                                     os.getpid(),
                                     random.randint(0,0x7FFFFFFF))
        if not self.quiet:
            self.outf.write('Renaming %s to %s\n' % (old_relpath, new_relpath))
        self.to_transport.rename(old_relpath, stamp)
        self._pending_renames.append((stamp, new_relpath))

    def finish_renames(self):
        for (stamp, new_path) in self._pending_renames:
            self.to_transport.rename(stamp, new_path)
        # The following shouldn't be needed since we use it once per upload,
        # but better safe than sorry ;-)
        self._pending_renames = []

    def upload_full_tree(self):
        self.to_transport.ensure_base() # XXX: Handle errors (add
                                        # --create-prefix option ?)
        self.tree.lock_read()
        try:
            for relpath, ie in self.tree.inventory.iter_entries():
                if relpath in ('', '.bzrignore'):
                    # skip root ('')
                    # .bzrignore has no meaning outside of a working tree
                    # so do not upload it
                    continue
                if ie.kind == 'file':
                    self.upload_file_robustly(relpath, ie.file_id)
                elif ie.kind == 'directory':
                    self.make_remote_dir_robustly(relpath)
                else:
                    raise NotImplementedError
            self.set_uploaded_revid(self.rev_id)
        finally:
            self.tree.unlock()

    def upload_tree(self):
        # If we can't find the revid file on the remote location, upload the
        # full tree instead
        try:
            rev_id = self.get_uploaded_revid()
        except errors.NoSuchFile:
            if not self.quiet:
                self.outf.write('No uploaded revision id found,'
                                ' switching to full upload\n')
            self.upload_full_tree()
            # We're done
            return

        # Check if the revision hasn't already been uploaded
        if rev_id == self.rev_id:
            if not self.quiet:
                self.outf.write('Remote location already up to date\n')

        # XXX: errors out if rev_id not in branch history (probably someone
        # uploaded from a different branch).
        from_tree = self.branch.repository.revision_tree(rev_id)
        self.to_transport.ensure_base() # XXX: Handle errors (add
                                        # --create-prefix option ?)
        changes = self.tree.changes_from(from_tree)
        self.tree.lock_read()
        try:
            for (path, id, kind) in changes.removed:
                if kind is 'file':
                    self.delete_remote_file(path)
                elif kind is  'directory':
                    self.delete_remote_dir_maybe(path)
                else:
                    raise NotImplementedError

            for (old_path, new_path, id, kind,
                 content_change, exec_change) in changes.renamed:
                if content_change:
                    # We update the old_path content because renames and
                    # deletions are differed.
                    self.upload_file(old_path, id)
                self.rename_remote(old_path, new_path)
            self.finish_renames()
            self.finish_deletions()

            for (path, id, old_kind, new_kind) in changes.kind_changed:
                if old_kind is 'file':
                    self.delete_remote_file(path)
                elif old_kind is  'directory':
                    self.delete_remote_dir(path)
                else:
                    raise NotImplementedError

                if new_kind is 'file':
                    self.upload_file(path, id)
                elif new_kind is 'directory':
                    self.make_remote_dir(path)
                else:
                    raise NotImplementedError

            for (path, id, kind) in changes.added:
                if kind is 'file':
                    self.upload_file(path, id)
                elif kind is 'directory':
                    self.make_remote_dir(path)
                else:
                    raise NotImplementedError

            # XXX: Add a test for exec_change
            for (path, id, kind,
                 content_change, exec_change) in changes.modified:
                if kind is 'file':
                    self.upload_file(path, id)
                else:
                    raise NotImplementedError

            self.set_uploaded_revid(self.rev_id)
        finally:
            self.tree.unlock()


class CannotUploadToWorkingTreeError(errors.BzrCommandError):

    _fmt = 'Cannot upload to a bzr managed working tree: %(url)s".'


class cmd_upload(commands.Command):
    """Upload a working tree, as a whole or incrementally.

    If no destination is specified use the last one used.
    If no revision is specified upload the changes since the last upload.

    Changes include files added, renamed, modified or removed.
    """
    _see_also = ['plugins/upload']
    takes_args = ['location?']
    takes_options = [
        'revision',
        'remember',
        option.Option('full', 'Upload the full working tree.'),
        option.Option('quiet', 'Do not output what is being done.',
                       short_name='q'),
        option.Option('directory',
                      help='Branch to upload from, '
                      'rather than the one containing the working directory.',
                      short_name='d',
                      type=unicode,
                      ),
        option.Option('auto',
                      'Trigger an upload from this branch whenever the tip '
                      'revision changes.')
       ]

    def run(self, location=None, full=False, revision=None, remember=None,
            directory=None, quiet=False, auto=None
            ):
        if directory is None:
            directory = u'.'

        if auto and not auto_hook_available:
            raise BzrCommandError("Your version of bzr does not have the "
                    "hooks necessary for --auto to work")

        (wt, branch,
         relpath) = bzrdir.BzrDir.open_containing_tree_or_branch(directory)

        if wt:
            changes = wt.changes_from(wt.basis_tree())

            if revision is None and  changes.has_changed():
                raise errors.UncommittedChanges(wt)

        if location is None:
            stored_loc = get_upload_location(branch)
            if stored_loc is None:
                raise errors.BzrCommandError('No upload location'
                                             ' known or specified.')
            else:
                # FIXME: Not currently tested
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        to_transport = transport.get_transport(location)

        # Check that we are not uploading to a existing working tree.
        try:
            to_bzr_dir = bzrdir.BzrDir.open_from_transport(to_transport)
            has_wt = to_bzr_dir.has_workingtree()
        except errors.NotBranchError:
            has_wt = False
        except errors.NotLocalUrl:
            # The exception raised is a bit weird... but that's life.
            has_wt = True

        if has_wt:
            raise CannotUploadToWorkingTreeError(url=location)

        if revision is None:
            rev_id = branch.last_revision()
        else:
            if len(revision) != 1:
                raise errors.BzrCommandError(
                    'bzr upload --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(branch).rev_id

        tree = branch.repository.revision_tree(rev_id)

        uploader = BzrUploader(branch, to_transport, self.outf, tree,
                               rev_id, quiet=quiet)

        if full:
            uploader.upload_full_tree()
        else:
            uploader.upload_tree()

        # We uploaded successfully, remember it
        if get_upload_location(branch) is None or remember:
            set_upload_location(branch, to_transport.base)
        if auto is not None:
            set_upload_auto(branch, auto)


commands.register_command(cmd_upload)

def install_auto_upload_hook():
    from bzrlib.plugins.upload import auto_upload_hook
    branch.Branch.hooks.install_named_hook('post_change_branch_tip',
            auto_upload_hook.auto_upload_hook,
            'Auto upload code from a branch when it is changed.')


if hasattr(branch.Branch.hooks, "install_named_hook"):
    install_auto_upload_hook()
    auto_hook_available = True
else:
    auto_hook_available = False


def load_tests(basic_tests, module, loader):
    # This module shouldn't define any tests but I don't know how to report
    # that. I prefer to update basic_tests with the other tests to detect
    # unwanted tests and I think that's sufficient.

    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
