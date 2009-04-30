# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
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


"""An adapter between a Git index and a Bazaar Working Tree"""


from cStringIO import (
    StringIO,
    )
from dulwich.index import (
    Index,
    )
from dulwich.objects import (
    Blob,
    )
import os
import stat

from bzrlib import (
    errors,
    inventory,
    lockable_files,
    lockdir,
    osutils,
    transport,
    urlutils,
    workingtree,
    )
from bzrlib.decorators import (
    needs_read_lock,
    needs_write_lock,
    )


from bzrlib.plugins.git.inventory import (
    GitIndexInventory,
    )


class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, bzrdir, repo, branch):
        self.basedir = bzrdir.root_transport.local_abspath('.')
        self.bzrdir = bzrdir
        self.repository = repo
        self.mapping = self.repository.get_mapping()
        self._branch = branch
        self._transport = bzrdir.transport

        self.controldir = urlutils.join(self.repository._git._controldir, 'bzr')

        try:
            os.makedirs(self.controldir)
            os.makedirs(os.path.join(self.controldir, 'lock'))
        except OSError:
            pass

        self._control_files = lockable_files.LockableFiles(
            transport.get_transport(self.controldir), 'lock', lockdir.LockDir)

        self._format = GitWorkingTreeFormat()

        self.index_path = os.path.join(self.repository._git.controldir(), 
                                       "index")
        self.index = Index(self.index_path)
        self.views = self._make_views()
        self._detect_case_handling()

    def unlock(self):
        # non-implementation specific cleanup
        self._cleanup()

        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def is_control_filename(self, path):
        return os.path.basename(path) == ".git"

    def _rewrite_index(self):
        self.index.clear()
        for path, entry in self._inventory.iter_entries():
            if entry.kind == "directory":
                # Git indexes don't contain directories
                continue
            if entry.kind == "file":
                blob = Blob()
                try:
                    file, stat_val = self.get_file_with_stat(entry.file_id, path)
                except (errors.NoSuchFile, IOError):
                    # TODO: Rather than come up with something here, use the old index
                    file = StringIO()
                    stat_val = (0, 0, 0, 0, stat.S_IFREG | 0644, 0, 0, 0, 0, 0)
                blob._text = file.read()
            elif entry.kind == "symlink":
                blob = Blob()
                stat_val = os.stat(self.abspath(path))
                blob._text = entry.symlink_target
            # Add object to the repository if it didn't exist yet
            if not blob.id in self.repository._git.object_store:
                self.repository._git.object_store.add_object(blob)
            # Add an entry to the index or update the existing entry
            (mode, ino, dev, links, uid, gid, size, atime, mtime, ctime) = stat_val
            flags = 0
            self.index[path.encode("utf-8")] = (ctime, mtime, ino, dev, mode, uid, gid, size, blob.id, flags)

    def flush(self):
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self._rewrite_index()           
        self.index.write()
        self._inventory_is_modified = False

    def _reset_data(self):
        self._inventory_is_modified = False
        basis_inv = self.repository.get_inventory(self.mapping.revision_id_foreign_to_bzr(self.repository._git.head()))
        result = GitIndexInventory(basis_inv, self.mapping, self.index)
        self._set_inventory(result, dirty=False)

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return osutils.sha_file_by_name(self.abspath(path).encode(osutils._fs_enc))


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    def get_format_description(self):
        return "Git Working Tree"
