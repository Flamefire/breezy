# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git Branch and a Bazaar Branch"""

from dulwich.objects import (
    Commit,
    Tag,
    )

from bzrlib import (
    branch,
    config,
    foreign,
    repository,
    revision,
    tag,
    transport,
    )
from bzrlib.decorators import (
    needs_read_lock,
    )
from bzrlib.trace import (
    is_quiet,
    mutter,
    )

from bzrlib.plugins.git.config import (
    GitBranchConfig,
    )
from bzrlib.plugins.git.errors import (
    NoSuchRef,
    )

try:
    from bzrlib.foreign import ForeignBranch
except ImportError:
    class ForeignBranch(branch.Branch):
        def __init__(self, mapping):
            self.mapping = mapping
            super(ForeignBranch, self).__init__()


class GitPullResult(branch.PullResult):

    def _lookup_revno(self, revid):
        assert isinstance(revid, str), "was %r" % revid
        # Try in source branch first, it'll be faster
        return self.target_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class LocalGitTagDict(tag.BasicTags):
    """Dictionary with tags in a local repository."""

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_tag_dict(self):
        ret = {}
        for k,v in self.repository._git.tags.iteritems():
            obj = self.repository._git.get_object(v)
            while isinstance(obj, Tag):
                v = obj.object[1]
                obj = self.repository._git.get_object(v)
            if not isinstance(obj, Commit):
                mutter("Tag %s points at object %r that is not a commit, "
                       "ignoring", k, obj)
                continue
            ret[k] = self.branch.mapping.revision_id_foreign_to_bzr(v)
        return ret

    def set_tag(self, name, revid):
        self.repository._git.tags[name] = revid


class GitBranchFormat(branch.BranchFormat):

    def get_format_description(self):
        return 'Git Branch'

    def supports_tags(self):
        return True

    def make_tags(self, branch):
        if getattr(branch.repository, "get_refs", None) is not None:
            from bzrlib.plugins.git.remote import RemoteGitTagDict
            return RemoteGitTagDict(branch)
        else:
            return LocalGitTagDict(branch)


class GitBranch(ForeignBranch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, bzrdir, repository, name, head, lockfiles):
        self.repository = repository
        self._format = GitBranchFormat()
        self.control_files = lockfiles
        self.bzrdir = bzrdir
        super(GitBranch, self).__init__(repository.get_mapping())
        self.name = name
        self.head = head
        self.base = bzrdir.transport.base

    def _get_nick(self, local=False, possible_master_transports=None):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        return self.name

    def _set_nick(self, nick):
        raise NotImplementedError

    nick = property(_get_nick, _set_nick)

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.repository.base, self.name)

    def dpull(self, source, stop_revision=None):
        if stop_revision is None:
            stop_revision = source.last_revision()
        # FIXME: Check for diverged branches
        revidmap = self.repository.dfetch(source.repository, stop_revision)
        if revidmap != {}:
            self.generate_revision_history(revidmap[stop_revision])
        return revidmap

    def generate_revision_history(self, revid, old_revid=None):
        # FIXME: Check that old_revid is in the ancestry of revid
        newhead, self.mapping = self.mapping.revision_id_bzr_to_foreign(revid)
        self._set_head(newhead)

    def _set_head(self, head):
        self.head = head
        self.repository._git.set_ref(self.name, self.head)

    def lock_write(self):
        self.control_files.lock_write()

    def get_stacked_on_url(self):
        # Git doesn't do stacking (yet...)
        return None

    def get_parent(self):
        """See Branch.get_parent()."""
        # FIXME: Set "origin" url from .git/config ?
        return None

    def set_parent(self, url):
        # FIXME: Set "origin" url in .git/config ?
        pass

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()

    def get_physical_lock_status(self):
        return False

 
class LocalGitBranch(GitBranch):
    """A local Git branch."""

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        if self.head is None:
            return revision.NULL_REVISION
        return self.mapping.revision_id_foreign_to_bzr(self.head)

    def _get_checkout_format(self):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        format = self.repository.bzrdir.checkout_metadir()
        format.set_branch_format(self._format)
        return format

    def create_checkout(self, to_location, revision_id=None, lightweight=False,
        accelerator_tree=None, hardlink=False):
        if lightweight:
            t = transport.get_transport(to_location)
            t.ensure_base()
            format = self._get_checkout_format()
            checkout = format.initialize_on_transport(t)
            from_branch = branch.BranchReferenceFormat().initialize(checkout, 
                self)
            tree = checkout.create_workingtree(revision_id,
                from_branch=from_branch, hardlink=hardlink)
            return tree
        else:
            return self._create_heavyweight_checkout(to_location, revision_id,
            hardlink)

    def _create_heavyweight_checkout(self, to_location, revision_id=None, 
                                     hardlink=False):
        """Create a new heavyweight checkout of this branch.

        :param to_location: URL of location to create the new checkout in.
        :param revision_id: Revision that should be the tip of the checkout.
        :param hardlink: Whether to hardlink
        :return: WorkingTree object of checkout.
        """
        checkout_branch = BzrDir.create_branch_convenience(
            to_location, force_new_tree=False, format=get_rich_root_format())
        checkout = checkout_branch.bzrdir
        checkout_branch.bind(self)
        # pull up to the specified revision_id to set the initial 
        # branch tip correctly, and seed it with history.
        checkout_branch.pull(self, stop_revision=revision_id)
        return checkout.create_workingtree(revision_id, hardlink=hardlink)

    def _gen_revision_history(self):
        if self.head is None:
            return []
        ret = list(self.repository.iter_reverse_revision_history(
            self.last_revision()))
        ret.reverse()
        return ret

    def get_config(self):
        return GitBranchConfig(self)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location,
                                          store=config.STORE_LOCATION)

    def supports_tags(self):
        return True


class GitBranchPullResult(branch.PullResult):

    def report(self, to_file):
        if not is_quiet():
            if self.old_revid == self.new_revid:
                to_file.write('No revisions to pull.\n')
            else:
                to_file.write('Now on revision %d (git sha: %s).\n' % 
                        (self.new_revno, self.new_git_head))
        self._show_tag_conficts(to_file)


class InterGitGenericBranch(branch.InterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    @classmethod
    def is_compatible(self, source, target):
        return (isinstance(source, GitBranch) and 
                not isinstance(target, GitBranch))

    def update_revisions(self, stop_revision=None, overwrite=False,
        graph=None):
        """See InterBranch.update_revisions()."""
        interrepo = repository.InterRepository.get(self.source.repository, 
            self.target.repository)
        self._head = None
        self._last_revid = None
        def determine_wants(heads):
            if not self.source.name in heads:
                raise NoSuchRef(self.source.name, heads.keys())
            if stop_revision is not None:
                self._last_revid = stop_revision
                self._head, mapping = self.source.repository.lookup_git_revid(
                    stop_revision)
            else:
                self._head = heads[self.source.name]
                self._last_revid = \
                    self.source.mapping.revision_id_foreign_to_bzr(self._head)
            if self.target.repository.has_revision(self._last_revid):
                return []
            return [self._head]
        interrepo.fetch_objects(determine_wants, self.source.mapping)
        if overwrite:
            prev_last_revid = None
        else:
            prev_last_revid = self.target.last_revision()
        self.target.generate_revision_history(self._last_revid, prev_last_revid)

    def pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, _hook_master=None, run_hooks=True,
             _override_hook_target=None):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        """
        result = GitBranchPullResult()
        result.source_branch = self.source
        if _override_hook_target is None:
            result.target_branch = self.target
        else:
            result.target_branch = _override_hook_target
        self.source.lock_read()
        try:
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            graph = self.target.repository.get_graph(self.source.repository)
            result.old_revno, result.old_revid = \
                self.target.last_revision_info()
            self.update_revisions(stop_revision, overwrite=overwrite, 
                graph=graph)
            result.new_git_head = self._head
            result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
                overwrite)
            result.new_revno, result.new_revid = self.target.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in branch.Branch.hooks['post_pull']:
                    hook(result)
        finally:
            self.source.unlock()
        return result




branch.InterBranch.register_optimiser(InterGitGenericBranch)


class InterGitRemoteLocalBranch(branch.InterBranch):
    """InterBranch implementation that pulls between Git branches."""

    @classmethod
    def is_compatible(self, source, target):
        from bzrlib.plugins.git.remote import RemoteGitBranch
        return (isinstance(source, RemoteGitBranch) and 
                isinstance(target, LocalGitBranch))

    def pull(self, stop_revision=None, overwrite=False, 
        possible_transports=None):
        result = GitPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        interrepo = repository.InterRepository.get(self.source.repository, 
            self.target.repository)
        result.old_revid = self.target.last_revision()
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        interrepo.fetch(revision_id=stop_revision)
        self.target.generate_revision_history(stop_revision, result.old_revid)
        result.new_revid = self.target.last_revision()
        return result


branch.InterBranch.register_optimiser(InterGitRemoteLocalBranch)
