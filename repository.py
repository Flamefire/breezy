# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2008-2009 Jelmer Vernooij <jelmer@samba.org>
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

"""An adapter between a Git Repository and a Bazaar Branch"""

from bzrlib import (
    errors,
    inventory,
    repository,
    revision,
    revisiontree,
    )
from bzrlib.foreign import (
    ForeignRepository,
    )

from bzrlib.plugins.git.commit import (
    GitCommitBuilder,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    foreign_git,
    mapping_registry,
    )
from bzrlib.plugins.git.tree import (
    GitRevisionTree,
    )
from bzrlib.plugins.git.versionedfiles import (
    GitRevisions,
    GitTexts,
    )


from dulwich.objects import (
    Commit,
    )


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    _serializer = None
    _commit_builder_class = GitCommitBuilder
    vcs = foreign_git

    def __init__(self, gitdir, lockfiles):
        ForeignRepository.__init__(self, GitRepositoryFormat(), gitdir,
            lockfiles)
        from bzrlib.plugins.git import fetch, push
        for optimiser in [fetch.InterRemoteGitNonGitRepository,
                          fetch.InterLocalGitNonGitRepository,
                          fetch.InterGitGitRepository,
                          push.InterToLocalGitRepository,
                          push.InterToRemoteGitRepository]:
            repository.InterRepository.register_optimiser(optimiser)

    def is_shared(self):
        return False

    def supports_rich_root(self):
        return True

    def _warn_if_deprecated(self, branch=None):
        # This class isn't deprecated
        pass

    def get_mapping(self):
        return default_mapping

    def make_working_trees(self):
        return True

    def revision_graph_can_have_wrong_parents(self):
        return False

    def dfetch(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.dfetch(stop_revision)

    def dfetch_refs(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.dfetch_refs(stop_revision)

    def fetch_refs(self, source, stop_revision):
        interrepo = repository.InterRepository.get(source, self)
        return interrepo.fetch_refs(stop_revision)


class LocalGitRepository(GitRepository):
    """Git repository on the file system."""

    def __init__(self, gitdir, lockfiles):
        GitRepository.__init__(self, gitdir, lockfiles)
        self.base = gitdir.root_transport.base
        self._git = gitdir._git
        self.signatures = None
        self.revisions = GitRevisions(self, self._git.object_store)
        self.inventories = None
        self.texts = GitTexts(self)

    def _iter_revision_ids(self):
        for sha in self._git.object_store:
            o = self._git.object_store[sha]
            if not isinstance(o, Commit):
                continue
            rev = self.get_mapping().import_commit(o,
                self.lookup_foreign_revision_id)
            yield o.id, rev.revision_id

    def all_revision_ids(self):
        ret = set([])
        for git_sha, revid in self._iter_revision_ids():
            ret.add(revid)
        return ret

    def get_parent_map(self, revids):
        parent_map = {}
        for revision_id in revids:
            assert isinstance(revision_id, str)
            if revision_id == revision.NULL_REVISION:
                parent_map[revision_id] = ()
                continue
            hexsha, mapping = self.lookup_bzr_revision_id(revision_id)
            try:
                commit = self._git[hexsha]
            except KeyError:
                continue
            parent_map[revision_id] = [self.lookup_foreign_revision_id(p, mapping) for p in commit.parents]
        return parent_map

    def get_ancestry(self, revision_id, topo_sorted=True):
        """See Repository.get_ancestry().
        """
        if revision_id is None:
            return [None, revision.NULL_REVISION] + self._all_revision_ids()
        assert isinstance(revision_id, str)
        ancestry = []
        graph = self.get_graph()
        for rev, parents in graph.iter_ancestry([revision_id]):
            ancestry.append(rev)
        ancestry.reverse()
        return [None] + ancestry

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def lookup_foreign_revision_id(self, foreign_revid, mapping=None):
        """Lookup a revision id.

        """
        if mapping is None:
            mapping = self.get_mapping()
        commit = self._git[foreign_revid]
        rev = mapping.import_commit(commit, lambda x: None)
        return rev.revision_id

    def has_signature_for_revision_id(self, revision_id):
        return False

    def lookup_bzr_revision_id(self, bzr_revid):
        try:
            return mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId:
            mapping = self.get_mapping()
            try:
                return self._git.refs[mapping.revid_as_refname(bzr_revid)], mapping
            except KeyError:
                # Update refs from Git commit objects
                # FIXME: Hitting this a lot will be very inefficient...
                for git_sha, bzr_revid in self._iter_revision_ids():
                    self._git.refs[mapping.revid_as_refname(bzr_revid)] = git_sha
                try:
                    return self._git.refs[mapping.revid_as_refname(bzr_revid)], mapping
                except KeyError:
                    raise errors.NoSuchRevision(self, bzr_revid)

    def get_revision(self, revision_id):
        git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        try:
            commit = self._git[git_commit_id]
        except KeyError:
            raise errors.NoSuchRevision(self, revision_id)
        # print "fetched revision:", git_commit_id
        revision = mapping.import_commit(commit,
            self.lookup_foreign_revision_id)
        assert revision is not None
        return revision

    def has_revision(self, revision_id):
        try:
            git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        except errors.NoSuchRevision:
            return False
        return (git_commit_id in self._git)

    def has_revisions(self, revision_ids):
        return set((self.has_revision(revid) for revid in revision_ids))

    def get_revisions(self, revids):
        return [self.get_revision(r) for r in revids]

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        revision_id = revision.ensure_null(revision_id)
        if revision_id == revision.NULL_REVISION:
            inv = inventory.Inventory(root_id=None)
            inv.revision_id = revision_id
            return revisiontree.RevisionTree(self, inv, revision_id)
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def set_make_working_trees(self, trees):
        pass

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
        progress=None):
        return self._git.fetch_objects(determine_wants, graph_walker, progress)

    def _get_versioned_file_checker(self, text_key_references=None,
                        ancestors=None):
        return GitVersionedFileChecker(self,
            text_key_references=text_key_references, ancestors=ancestors)
    

class GitVersionedFileChecker(repository._VersionedFileChecker):

    file_ids = []

    def _check_file_version_parents(self, texts, progress_bar):
        return {}, []


class GitRepositoryFormat(repository.RepositoryFormat):
    """Git repository format."""

    supports_tree_reference = False
    rich_root_data = True

    def get_format_description(self):
        return "Git Repository"

    def initialize(self, url, shared=False, _internal=False):
        raise errors.UninitializableFormat(self)

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

    def get_foreign_tests_repository_factory(self):
        from bzrlib.plugins.git.tests.test_repository import (
            ForeignTestsRepositoryFactory,
            )
        return ForeignTestsRepositoryFactory()

    def network_name(self):
        return "git"
