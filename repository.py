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
    check,
    errors,
    graph as _mod_graph,
    inventory,
    repository,
    revision,
    transactions,
    version_info as bzrlib_version,
    )
from bzrlib.decorators import only_raises
try:
    from bzrlib.revisiontree import InventoryRevisionTree
except ImportError: # bzr < 2.4
    from bzrlib.revisiontree import RevisionTree as InventoryRevisionTree
from bzrlib.foreign import (
    ForeignRepository,
    )

from bzrlib.plugins.git.commit import (
    GitCommitBuilder,
    )
from bzrlib.plugins.git.errors import (
    NotCommitError,
    )
from bzrlib.plugins.git.filegraph import (
    GitFileLastChangeScanner,
    GitFileParentProvider,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    foreign_vcs_git,
    mapping_registry,
    )
from bzrlib.plugins.git.tree import (
    GitRevisionTree,
    )


from dulwich.objects import (
    Commit,
    Tag,
    ZERO_SHA,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )


class RepoReconciler(object):
    """Reconciler that reconciles a repository.

    """

    def __init__(self, repo, other=None, thorough=False):
        """Construct a RepoReconciler.

        :param thorough: perform a thorough check which may take longer but
                         will correct non-data loss issues such as incorrect
                         cached data.
        """
        self.repo = repo

    def reconcile(self):
        """Perform reconciliation.

        After reconciliation the following attributes document found issues:
        inconsistent_parents: The number of revisions in the repository whose
                              ancestry was being reported incorrectly.
        garbage_inventories: The number of inventory objects without revisions
                             that were garbage collected.
        """


class GitCheck(check.Check):

    def __init__(self, repository, check_repo=True):
        self.repository = repository
        self.checked_rev_cnt = 0

    def check(self, callback_refs=None, check_repo=True):
        if callback_refs is None:
            callback_refs = {}
        self.repository.lock_read()
        self.repository.unlock()

    def report_results(self, verbose):
        pass


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    _serializer = None
    vcs = foreign_vcs_git
    chk_bytes = None

    def __init__(self, gitdir):
        if bzrlib_version >= (2, 5):
            control_files = None
        else:
            class DummyControlFiles(object):
                def __init__(self):
                    self._transport = gitdir.root_transport
            control_files = DummyControlFiles()
        super(GitRepository, self).__init__(GitRepositoryFormat(),
            gitdir, control_files)
        self._transport = gitdir.root_transport
        from bzrlib.plugins.git import fetch, push
        for optimiser in [fetch.InterRemoteGitNonGitRepository,
                          fetch.InterLocalGitNonGitRepository,
                          fetch.InterGitGitRepository,
                          push.InterToLocalGitRepository,
                          push.InterToRemoteGitRepository]:
            repository.InterRepository.register_optimiser(optimiser)
        self._lock_mode = None
        self._lock_count = 0

    def add_fallback_repository(self, basis_url):
        raise errors.UnstackableRepositoryFormat(self._format,
            self.control_transport.base)

    def is_shared(self):
        return False

    def get_physical_lock_status(self):
        return False

    def lock_write(self):
        """See Branch.lock_write()."""
        if self._lock_mode:
            assert self._lock_mode == 'w'
            self._lock_count += 1
        else:
            self._lock_mode = 'w'
            self._lock_count = 1
        return GitRepositoryLock(self)

    def dont_leave_lock_in_place(self):
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def leave_lock_in_place(self):
        raise NotImplementedError(self.leave_lock_in_place)

    def lock_read(self):
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w')
            self._lock_count += 1
        else:
            self._lock_mode = 'r'
            self._lock_count = 1
        return self

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self._lock_count == 0:
            raise errors.LockNotHeld(self)
        if self._lock_count == 1 and self._lock_mode == 'w':
            if self._write_group is not None:
                self.abort_write_group()
                self._lock_count -= 1
                self._lock_mode = None
                raise errors.BzrError(
                    'Must end write groups before releasing write locks.')
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None

    def is_write_locked(self):
        return (self._lock_mode == 'w')

    def is_locked(self):
        return (self._lock_mode is not None)

    def get_transaction(self):
        """See Repository.get_transaction()."""
        if self._write_group is None:
            return transactions.PassThroughTransaction()
        else:
            return self._write_group

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        reconciler = RepoReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def supports_rich_root(self):
        return True

    def _warn_if_deprecated(self, branch=None): # for bzr < 2.4
        # This class isn't deprecated
        pass

    def get_mapping(self):
        return default_mapping

    def make_working_trees(self):
        return not self._git.bare

    def revision_graph_can_have_wrong_parents(self):
        return False

    def add_signature_text(self, revid, signature):
        raise errors.UnsupportedOperation(self.add_signature_text, self)


class GitRepositoryLock(object):
    """Subversion lock."""

    def __init__(self, repository):
        self.repository_token = None
        self.repository = repository

    def unlock(self):
        self.repository.unlock()


class LocalGitRepository(GitRepository):
    """Git repository on the file system."""

    def __init__(self, gitdir):
        GitRepository.__init__(self, gitdir)
        self.base = gitdir.root_transport.base
        self._git = gitdir._git
        self._file_change_scanner = GitFileLastChangeScanner(self)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None, lossy=False):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        self.start_write_group()
        return GitCommitBuilder(self, parents, config,
            timestamp, timezone, committer, revprops, revision_id,
            lossy)

    def get_file_graph(self):
        return _mod_graph.Graph(GitFileParentProvider(
            self._file_change_scanner))

    def iter_files_bytes(self, desired_files):
        """Iterate through file versions.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        bytes_iterator is an iterable of bytestrings for the file.  The
        kind of iterable and length of the bytestrings are unspecified, but for
        this implementation, it is a list of bytes produced by
        VersionedFile.get_record_stream().

        :param desired_files: a list of (file_id, revision_id, identifier)
            triples
        """
        per_revision = {}
        for (file_id, revision_id, identifier) in desired_files:
            per_revision.setdefault(revision_id, []).append(
                (file_id, identifier))
        for revid, files in per_revision.iteritems():
            (commit_id, mapping) = self.lookup_bzr_revision_id(revid)
            try:
                commit = self._git.object_store[commit_id]
            except KeyError:
                raise errors.RevisionNotPresent(revid, self)
            root_tree = commit.tree
            for fileid, identifier in files:
                path = mapping.parse_file_id(fileid)
                try:
                    obj = tree_lookup_path(
                        self._git.object_store.__getitem__, root_tree, path)
                    if isinstance(obj, tuple):
                        (mode, item_id) = obj
                        obj = self._git.object_store[item_id]
                except KeyError:
                    raise errors.RevisionNotPresent((fileid, revid), self)
                else:
                    if obj.type_name == "tree":
                        yield (identifier, [])
                    elif obj.type_name == "blob":
                        yield (identifier, obj.chunked)
                    else:
                        raise AssertionError("file text resolved to %r" % obj)

    def _iter_revision_ids(self):
        mapping = self.get_mapping()
        for sha in self._git.object_store:
            o = self._git.object_store[sha]
            if not isinstance(o, Commit):
                continue
            rev, roundtrip_revid, verifiers = mapping.import_commit(o,
                mapping.revision_id_foreign_to_bzr)
            yield o.id, rev.revision_id, roundtrip_revid

    def all_revision_ids(self):
        ret = set([])
        for git_sha, revid, roundtrip_revid in self._iter_revision_ids():
            if roundtrip_revid:
                ret.add(roundtrip_revid)
            else:
                ret.add(revid)
        return ret

    def _get_parents(self, revid):
        if type(revid) != str:
            raise ValueError
        try:
            (hexsha, mapping) = self.lookup_bzr_revision_id(revid)
        except errors.NoSuchRevision:
            return None
        try:
            commit = self._git[hexsha]
        except KeyError:
            return None
        return [
            self.lookup_foreign_revision_id(p, mapping)
            for p in commit.parents]

    def get_parent_map(self, revids):
        parent_map = {}
        for revision_id in revids:
            parents = self._get_parents(revision_id)
            if revision_id == revision.NULL_REVISION:
                parent_map[revision_id] = ()
                continue
            if parents is None:
                continue
            if len(parents) == 0:
                parents = [revision.NULL_REVISION]
            parent_map[revision_id] = tuple(parents)
        return parent_map

    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors.
        """
        pending = set(revision_ids)
        parent_map = {}
        while pending:
            this_parent_map = {}
            for revid in pending:
                if revid == revision.NULL_REVISION:
                    continue
                parents = self._get_parents(revid)
                if parents is not None:
                    this_parent_map[revid] = parents
            parent_map.update(this_parent_map)
            pending = set()
            map(pending.update, this_parent_map.itervalues())
            pending = pending.difference(parent_map)
        return _mod_graph.KnownGraph(parent_map)

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        result = GitCheck(self, check_repo=check_repo)
        result.check(callback_refs)
        return result

    def pack(self, hint=None, clean_obsolete_packs=False):
        self._git.object_store.pack_loose_objects()

    def lookup_foreign_revision_id(self, foreign_revid, mapping=None):
        """Lookup a revision id.

        """
        assert type(foreign_revid) is str
        if mapping is None:
            mapping = self.get_mapping()
        if foreign_revid == ZERO_SHA:
            return revision.NULL_REVISION
        commit = self._git.object_store[foreign_revid]
        while isinstance(commit, Tag):
            commit = self._git[commit.object[1]]
        if not isinstance(commit, Commit):
            raise NotCommitError(commit.id)
        rev, roundtrip_revid, verifiers = mapping.import_commit(commit,
            mapping.revision_id_foreign_to_bzr)
        # FIXME: check testament before doing this?
        if roundtrip_revid:
            return roundtrip_revid
        else:
            return rev.revision_id

    def has_signature_for_revision_id(self, revision_id):
        """Check whether a GPG signature is present for this revision.

        This is never the case for Git repositories.
        """
        return False

    def lookup_bzr_revision_id(self, bzr_revid, mapping=None):
        """Lookup a bzr revision id in a Git repository.

        :param bzr_revid: Bazaar revision id
        :param mapping: Optional mapping to use
        :return: Tuple with git commit id, mapping that was used and supplement
            details
        """
        try:
            (git_sha, mapping) = mapping_registry.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId:
            if mapping is None:
                mapping = self.get_mapping()
            try:
                return (self._git.refs[mapping.revid_as_refname(bzr_revid)],
                        mapping)
            except KeyError:
                # Update refs from Git commit objects
                # FIXME: Hitting this a lot will be very inefficient...
                for git_sha, revid, roundtrip_revid in self._iter_revision_ids():
                    if not roundtrip_revid:
                        continue
                    refname = mapping.revid_as_refname(roundtrip_revid)
                    self._git.refs[refname] = git_sha
                    if roundtrip_revid == bzr_revid:
                        return git_sha, mapping
                raise errors.NoSuchRevision(self, bzr_revid)
        else:
            return (git_sha, mapping)

    def get_revision(self, revision_id):
        if not isinstance(revision_id, str):
            raise errors.InvalidRevisionId(revision_id, self)
        git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        try:
            commit = self._git[git_commit_id]
        except KeyError:
            raise errors.NoSuchRevision(self, revision_id)
        revision, roundtrip_revid, verifiers = mapping.import_commit(
            commit, self.lookup_foreign_revision_id)
        assert revision is not None
        # FIXME: check verifiers ?
        if roundtrip_revid:
            revision.revision_id = roundtrip_revid
        return revision

    def has_revision(self, revision_id):
        """See Repository.has_revision."""
        if revision_id == revision.NULL_REVISION:
            return True
        try:
            git_commit_id, mapping = self.lookup_bzr_revision_id(revision_id)
        except errors.NoSuchRevision:
            return False
        return (git_commit_id in self._git)

    def has_revisions(self, revision_ids):
        """See Repository.has_revisions."""
        return set(filter(self.has_revision, revision_ids))

    def get_revisions(self, revids):
        """See Repository.get_revisions."""
        return [self.get_revision(r) for r in revids]

    def revision_trees(self, revids):
        """See Repository.revision_trees."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree."""
        revision_id = revision.ensure_null(revision_id)
        if revision_id == revision.NULL_REVISION:
            inv = inventory.Inventory(root_id=None)
            inv.revision_id = revision_id
            return InventoryRevisionTree(self, inv, revision_id)
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        raise NotImplementedError(self.get_inventory)

    def set_make_working_trees(self, trees):
        raise errors.UnsupportedOperation(self.set_make_working_trees, self)
        # TODO: Set bare= in the configuration bug=777065

    def fetch_objects(self, determine_wants, graph_walker, resolve_ext_ref,
        progress=None):
        return self._git.fetch_objects(determine_wants, graph_walker, progress)


class GitRepositoryFormat(repository.RepositoryFormat):
    """Git repository format."""

    supports_versioned_directories = False
    supports_tree_reference = False
    rich_root_data = True
    supports_leaving_lock = False
    fast_deltas = True
    supports_funky_characters = True
    supports_external_lookups = False
    supports_full_versioned_files = False
    supports_revision_signatures = False
    supports_nesting_repositories = False
    revision_graph_can_have_wrong_parents = False

    @property
    def _matchingbzrdir(self):
        from bzrlib.plugins.git.dir import LocalGitControlDirFormat
        return LocalGitControlDirFormat()

    def get_format_description(self):
        return "Git Repository"

    def initialize(self, controldir, shared=False, _internal=False):
        from bzrlib.plugins.git.dir import GitDir
        if not isinstance(controldir, GitDir):
            raise errors.UninitializableFormat(self)
        return controldir.open_repository()

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

    def get_foreign_tests_repository_factory(self):
        from bzrlib.plugins.git.tests.test_repository import (
            ForeignTestsRepositoryFactory,
            )
        return ForeignTestsRepositoryFactory()

    def network_name(self):
        return "git"
