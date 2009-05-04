# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

"""Push implementation that simply prints message saying push is not supported."""

from bzrlib import (
    ui,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )

from bzrlib.plugins.git.converter import (
    BazaarObjectStore,
    )
from bzrlib.plugins.git.errors import (
    NoPushSupport,
    )
from bzrlib.plugins.git.mapping import (
    inventory_to_tree_and_blobs,
    revision_to_commit,
    )
from bzrlib.plugins.git.repository import (
    GitRepository,
    LocalGitRepository,
    GitRepositoryFormat,
    )
from bzrlib.plugins.git.remote import (
    RemoteGitRepository,
    )


class MissingObjectsIterator(object):
    """Iterate over git objects that are missing from a target repository.

    """

    def __init__(self, source, mapping, pb=None):
        """Create a new missing objects iterator.

        """
        self.source = source
        self._object_store = BazaarObjectStore(self.source, mapping)
        self._revids = set()
        self._sent_shas = set()
        self._pending = []
        self.pb = pb

    def import_revisions(self, revids):
        self._revids.update(revids)
        for i, revid in enumerate(revids):
            if self.pb:
                self.pb.update("pushing revisions", i, len(revids))
            git_commit = self.import_revision(revid)
            yield (revid, git_commit)

    def need_sha(self, sha):
        if sha in self._sent_shas:
            return False
        (type, (fileid, revid)) = self._object_store._idmap.lookup_git_sha(sha)
        assert type in ("blob", "tree")
        if revid in self._revids:
            # Not sent yet, and part of the set of revisions to send
            return True
        # Not changed in the revisions to send, so either not necessary
        # or already present remotely (as git doesn't do ghosts)
        return False

    def queue(self, sha, obj, path, ie=None, inv=None):
        if obj is None:
            obj = (ie, inv)
        self._pending.append((obj, path))
        self._sent_shas.add(sha)

    def import_revision(self, revid):
        """Import the gist of a revision into this Git repository.

        """
        inv = self.source.get_inventory(revid)
        todo = [inv.root]
        tree_sha = None
        while todo:
            ie = todo.pop()
            (sha, object) = self._object_store._get_ie_object_or_sha1(ie, inv)
            if ie.parent_id is None:
                tree_sha = sha
            if not self.need_sha(sha):
                continue
            self.queue(sha, object, inv.id2path(ie.file_id), ie, inv)
            if ie.kind == "directory":
                todo.extend(ie.children.values())
        assert tree_sha is not None
        commit = self._object_store._get_commit(revid, tree_sha)
        self.queue(commit.id, commit, None)
        return commit.id

    def __len__(self):
        return len(self._pending)

    def __iter__(self):
        for i, (object, path) in enumerate(self._pending):
            if self.pb:
                self.pb.update("writing pack objects", i, len(self))
            if isinstance(object, tuple):
                object = self._object_store._get_ie_object(*object)
            yield (object, path)   


class InterToGitRepository(InterRepository):
    """InterRepository that copies into a Git repository."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
            fetch_spec=None):
        raise NoPushSupport()


class InterToLocalGitRepository(InterToGitRepository):

    def missing_revisions(self, stop_revision):
        if stop_revision is None:
            raise NotImplementedError
        missing = []
        pb = ui.ui_factory.nested_progress_bar()
        try:
            graph = self.source.get_graph()
            for revid, _ in graph.iter_ancestry([stop_revision]):
                pb.update("determining revisions to fetch", len(missing))
                if not self.target.has_revision(revid):
                    missing.append(revid)
            return graph.iter_topo_order(missing)
        finally:
            pb.finished()

    def dfetch(self, stop_revision=None):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        mapping = self.target.get_mapping()
        self.source.lock_read()
        try:
            todo = [revid for revid in self.missing_revisions(stop_revision) if revid != NULL_REVISION]
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = MissingObjectsIterator(self.source, mapping, pb)
                for old_bzr_revid, git_commit in object_generator.import_revisions(
                    todo):
                    new_bzr_revid = mapping.revision_id_foreign_to_bzr(git_commit)
                    revidmap[old_bzr_revid] = new_bzr_revid
                self.target._git.object_store.add_objects(object_generator) 
            finally:
                pb.finished()
        finally:
            self.source.unlock()
        return revidmap

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and 
                isinstance(target, LocalGitRepository))


class InterToRemoteGitRepository(InterToGitRepository):

    def dfetch(self, stop_revision=None):
        """Import the gist of the ancestry of a particular revision."""
        revidmap = {}
        mapping = self.target.get_mapping()
        self.source.lock_read()
        try:
            todo = [revid for revid in self.missing_revisions(stop_revision) if revid != NULL_REVISION]
            pb = ui.ui_factory.nested_progress_bar()
            try:
                object_generator = MissingObjectsIterator(self.source, mapping, pb)
                for old_bzr_revid, git_commit in object_generator.import_revisions(
                    todo):
                    new_bzr_revid = mapping.revision_id_foreign_to_bzr(git_commit)
                    revidmap[old_bzr_revid] = new_bzr_revid
                self.target._git.object_store.add_objects(object_generator) 
            finally:
                pb.finished()
        finally:
            self.source.unlock()
        return revidmap

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (not isinstance(source, GitRepository) and 
                isinstance(target, RemoteGitRepository))
