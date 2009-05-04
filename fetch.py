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

from cStringIO import (
    StringIO,
    )
import dulwich as git
from dulwich.client import (
    SimpleFetchGraphWalker,
    )
from dulwich.objects import (
    Commit,
    Tag,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )
import stat

from bzrlib import (
    debug,
    osutils,
    trace,
    ui,
    urlutils,
    )
from bzrlib.errors import (
    InvalidRevisionId,
    NoSuchId,
    NoSuchRevision,
    )
from bzrlib.inventory import (
    Inventory,
    InventoryDirectory,
    InventoryFile,
    InventoryLink,
    )
from bzrlib.lru_cache import (
    LRUCache,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.tsort import (
    topo_sort,
    )
from bzrlib.versionedfile import (
    FulltextContentFactory,
    )

from bzrlib.plugins.git.converter import (
    BazaarObjectStore,
    )
from bzrlib.plugins.git.mapping import (
    DEFAULT_FILE_MODE,
    inventory_to_tree_and_blobs,
    text_to_blob,
    )
from bzrlib.plugins.git.remote import (
    RemoteGitRepository,
    )
from bzrlib.plugins.git.repository import (
    GitRepository, 
    GitRepositoryFormat,
    LocalGitRepository,
    )


class BzrFetchGraphWalker(object):
    """GraphWalker implementation that uses a Bazaar repository."""

    def __init__(self, repository, mapping):
        self.repository = repository
        self.mapping = mapping
        self.done = set()
        self.heads = set(repository.all_revision_ids())
        self.parents = {}

    def __iter__(self):
        return iter(self.next, None)

    def ack(self, sha):
        revid = self.mapping.revision_id_foreign_to_bzr(sha)
        self.remove(revid)

    def remove(self, revid):
        self.done.add(revid)
        if revid in self.heads:
            self.heads.remove(revid)
        if revid in self.parents:
            for p in self.parents[revid]:
                self.remove(p)

    def next(self):
        while self.heads:
            ret = self.heads.pop()
            ps = self.repository.get_parent_map([ret])[ret]
            self.parents[ret] = ps
            self.heads.update([p for p in ps if not p in self.done])
            try:
                self.done.add(ret)
                return self.mapping.revision_id_bzr_to_foreign(ret)[0]
            except InvalidRevisionId:
                pass
        return None


def import_git_blob(texts, mapping, path, hexsha, base_inv, parent_id, 
    revision_id, parent_invs, shagitmap, lookup_object, executable, symlink):
    """Import a git blob object into a bzr repository.

    :param texts: VersionedFiles to add to
    :param path: Path in the tree
    :param blob: A git blob
    :return: Inventory delta for this file
    """
    file_id = mapping.generate_file_id(path)
    if symlink:
        cls = InventoryLink
    else:
        cls = InventoryFile
    # We just have to hope this is indeed utf-8:
    ie = cls(file_id, urlutils.basename(path).decode("utf-8"), parent_id)
    ie.executable = executable
    ie.text_id = hexsha
    # See if this has changed at all
    try:
        base_ie = base_inv[file_id]
    except NoSuchId:
        base_ie = None
        base_sha = None
    else:
        base_sha = base_ie.text_id
        try:
            if base_sha is None:
                base_sha = shagitmap.lookup_blob(file_id, base_ie.revision)
        except KeyError:
            base_sha = None
        else:
            if (base_sha == hexsha and base_ie.executable == ie.executable
                and base_ie.kind == ie.kind):
                # If nothing has changed since the base revision, we're done
                return [], []
    if base_sha == hexsha:
        ie.text_size = base_ie.text_size
        ie.text_sha1 = base_ie.text_sha1
        ie.symlink_target = base_ie.symlink_target
        ie.revision = base_ie.revision
    else:
        blob = lookup_object(hexsha)
        if ie.kind == "symlink":
            ie.symlink_target = blob.data
            ie.text_size = None
            ie.text_sha1 = None
        else:
            ie.text_size = len(blob.data)
            ie.text_sha1 = osutils.sha_string(blob.data)
    # Check what revision we should store
    parent_keys = []
    for pinv in parent_invs:
        if pinv.revision_id == base_inv.revision_id:
            pie = base_ie
            if pie is None:
                continue
        else:
            try:
                pie = pinv[file_id]
            except NoSuchId:
                continue
        if pie.text_sha1 == ie.text_sha1:
            # found a revision in one of the parents to use
            ie.revision = pie.revision
            break
        parent_keys.append((file_id, pie.revision))
    if ie.revision is None:
        # Need to store a new revision
        ie.revision = revision_id
        assert file_id is not None
        assert ie.revision is not None
        texts.insert_record_stream([FulltextContentFactory((file_id, ie.revision), tuple(parent_keys), ie.text_sha1, blob.data)])
        shamap = [(hexsha, "blob", (ie.file_id, ie.revision))]
    else:
        shamap = []
    if file_id in base_inv:
        old_path = base_inv.id2path(file_id)
    else:
        old_path = None
    return ([(old_path, path, file_id, ie)], shamap)


def import_git_tree(texts, mapping, path, hexsha, base_inv, parent_id, 
    revision_id, parent_invs, shagitmap, lookup_object):
    """Import a git tree object into a bzr repository.

    :param texts: VersionedFiles object to add to
    :param path: Path in the tree
    :param tree: A git tree object
    :param base_inv: Base inventory against which to return inventory delta
    :return: Inventory delta for this subtree
    """
    invdelta = []
    file_id = mapping.generate_file_id(path)
    # We just have to hope this is indeed utf-8:
    ie = InventoryDirectory(file_id, urlutils.basename(path.decode("utf-8")), 
        parent_id)
    ie.text_id = hexsha
    try:
        base_ie = base_inv[file_id]
    except NoSuchId:
        # Newly appeared here
        base_ie = None
        ie.revision = revision_id
        texts.add_lines((file_id, ie.revision), (), [])
        invdelta.append((None, path, file_id, ie))
    else:
        base_sha = base_ie.text_id
        # See if this has changed at all
        try:
            if base_sha is None:
                base_sha = shagitmap.lookup_tree(file_id, base_inv.revision_id)
        except KeyError:
            pass
        else:
            if base_sha == hexsha:
                # If nothing has changed since the base revision, we're done
                return [], {}, []
    # Remember for next time
    existing_children = set()
    child_modes = {}
    shamap = []
    tree = lookup_object(hexsha)
    for mode, name, child_hexsha in tree.entries():
        basename = name.decode("utf-8")
        existing_children.add(basename)
        child_path = osutils.pathjoin(path, name)
        if stat.S_ISDIR(mode):
            subinvdelta, grandchildmodes, subshamap = import_git_tree(texts, 
                    mapping, child_path, child_hexsha, base_inv, file_id, 
                    revision_id, parent_invs, shagitmap, lookup_object)
            invdelta.extend(subinvdelta)
            child_modes.update(grandchildmodes)
            shamap.extend(subshamap)
        else:
            fs_mode = stat.S_IMODE(mode)
            symlink = stat.S_ISLNK(mode)
            subinvdelta, subshamap = import_git_blob(texts, mapping, 
                    child_path, child_hexsha, base_inv, file_id, revision_id, 
                    parent_invs, shagitmap, lookup_object, 
                    bool(fs_mode & 0111), symlink)
            invdelta.extend(subinvdelta)
            shamap.extend(subshamap)
        if mode not in (stat.S_IFDIR, DEFAULT_FILE_MODE,
                        stat.S_IFLNK, DEFAULT_FILE_MODE|0111):
            child_modes[child_path] = mode
    # Remove any children that have disappeared
    if base_ie is not None:
        deletable = [v for k,v in base_ie.children.iteritems() if k not in existing_children]
        while deletable:
            ie = deletable.pop()
            invdelta.append((base_inv.id2path(ie.file_id), None, ie.file_id, None))
            if ie.kind == "directory":
                deletable.extend(ie.children.values())
    shamap.append((hexsha, "tree", (file_id, revision_id)))
    return invdelta, child_modes, shamap


def import_git_objects(repo, mapping, object_iter, target_git_object_retriever, 
        heads, pb=None):
    """Import a set of git objects into a bzr repository.

    :param repo: Bazaar repository
    :param mapping: Mapping to use
    :param object_iter: Iterator over Git objects.
    """
    # TODO: a more (memory-)efficient implementation of this
    graph = []
    root_trees = {}
    revisions = {}
    checked = set()
    heads = list(heads)
    parent_invs_cache = LRUCache(50)
    # Find and convert commit objects
    while heads:
        if pb is not None:
            pb.update("finding revisions to fetch", len(graph), None)
        head = heads.pop()
        assert isinstance(head, str)
        try:
            o = object_iter[head]
        except KeyError:
            continue
        if isinstance(o, Commit):
            rev = mapping.import_commit(o)
            if repo.has_revision(rev.revision_id):
                continue
            root_trees[rev.revision_id] = o.tree
            revisions[rev.revision_id] = rev
            graph.append((rev.revision_id, rev.parent_ids))
            target_git_object_retriever._idmap.add_entry(o.id, "commit", 
                    (rev.revision_id, o.tree))
            heads.extend([p for p in o.parents if p not in checked])
        elif isinstance(o, Tag):
            heads.append(o.object[1])
        else:
            trace.warning("Unable to import head object %r" % o)
        checked.add(head)
    # Order the revisions
    # Create the inventory objects
    for i, revid in enumerate(topo_sort(graph)):
        if pb is not None:
            pb.update("fetching revisions", i, len(graph))
        rev = revisions[revid]
        # We have to do this here, since we have to walk the tree and 
        # we need to make sure to import the blobs / trees with the right 
        # path; this may involve adding them more than once.
        def lookup_object(sha):
            try:
                return object_iter[sha]
            except KeyError:
                return target_git_object_retriever[sha]
        parent_invs = []
        for parent_id in rev.parent_ids:
            try:
                parent_invs.append(parent_invs_cache[parent_id])
            except KeyError:
                parent_inv = repo.get_inventory(parent_id)
                parent_invs.append(parent_inv)
                parent_invs_cache[parent_id] = parent_inv
        if parent_invs == []:
            base_inv = Inventory(root_id=None)
        else:
            base_inv = parent_invs[0]
        inv_delta, unusual_modes, shamap = import_git_tree(repo.texts, 
                mapping, "", root_trees[revid], base_inv, None, revid, 
                parent_invs, target_git_object_retriever._idmap, lookup_object)
        target_git_object_retriever._idmap.add_entries(shamap)
        if unusual_modes != {}:
            ret = "unusual modes: \n"
            for item in unusual_modes.iteritems():
                ret += "\t%s: %o\n" % item
            raise AssertionError(ret)
        try:
            basis_id = rev.parent_ids[0]
        except IndexError:
            basis_id = NULL_REVISION
        rev.inventory_sha1, inv = repo.add_inventory_by_delta(basis_id,
                  inv_delta, rev.revision_id, rev.parent_ids)
        parent_invs_cache[rev.revision_id] = inv
        repo.add_revision(rev.revision_id, rev)
        if "verify" in debug.debug_flags:
            objs = inventory_to_tree_and_blobs(inv, repo.texts, mapping)
            for sha1, newobj, path in objs:
                assert path is not None
                oldobj = tree_lookup_path(lookup_object, root_trees[revid], path)
                assert oldobj == newobj, "%r != %r in %s" % (oldobj, newobj, path)

    target_git_object_retriever._idmap.commit()


class InterGitNonGitRepository(InterRepository):
    """Base InterRepository that copies revisions from a Git into a non-Git 
    repository."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, mapping=None,
            fetch_spec=None):
        self.fetch_refs(revision_id=revision_id, pb=pb, find_ghosts=find_ghosts,
                mapping=mapping, fetch_spec=fetch_spec)

    def fetch_refs(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        if revision_id is not None:
            interesting_heads = [revision_id]
        elif fetch_spec is not None:
            interesting_heads = fetch_spec.heads
        else:
            interesting_heads = None
        self._refs = {}
        def determine_wants(refs):
            self._refs = refs
            if interesting_heads is None:
                ret = [sha for (ref, sha) in refs.iteritems() if not ref.endswith("^{}")]
            else:
                ret = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in interesting_heads if revid != NULL_REVISION]
            return [rev for rev in ret if not self.target.has_revision(mapping.revision_id_foreign_to_bzr(rev))]
        self.fetch_objects(determine_wants, mapping, pb)
        return self._refs



class InterRemoteGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a remote Git into a non-Git 
    repository."""

    def fetch_objects(self, determine_wants, mapping, pb=None):
        def progress(text):
            pb.update("git: %s" % text.rstrip("\r\n"), 0, 0)
        graph_walker = BzrFetchGraphWalker(self.target, mapping)
        create_pb = None
        if pb is None:
            create_pb = pb = ui.ui_factory.nested_progress_bar()
        target_git_object_retriever = BazaarObjectStore(self.target, mapping)
        recorded_wants = []

        def record_determine_wants(heads):
            wants = determine_wants(heads)
            recorded_wants.extend(wants)
            return wants
        
        try:
            self.target.lock_write()
            try:
                self.target.start_write_group()
                try:
                    objects_iter = self.source.fetch_objects(
                                record_determine_wants, 
                                graph_walker, 
                                target_git_object_retriever.get_raw, 
                                progress)
                    import_git_objects(self.target, mapping, objects_iter, 
                            target_git_object_retriever, recorded_wants, pb)
                finally:
                    self.target.commit_write_group()
            finally:
                self.target.unlock()
        finally:
            if create_pb:
                create_pb.finished()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return (isinstance(source, RemoteGitRepository) and 
                target.supports_rich_root() and
                not isinstance(target, GitRepository))


class InterLocalGitNonGitRepository(InterGitNonGitRepository):
    """InterRepository that copies revisions from a remote Git into a non-Git 
    repository."""

    def fetch_objects(self, determine_wants, mapping, pb=None):
        wants = determine_wants(self.source._git.get_refs())
        create_pb = None
        if pb is None:
            create_pb = pb = ui.ui_factory.nested_progress_bar()
        target_git_object_retriever = BazaarObjectStore(self.target, mapping)
        try:
            self.target.lock_write()
            try:
                self.target.start_write_group()
                try:
                    import_git_objects(self.target, mapping, 
                            self.source._git.object_store, 
                            target_git_object_retriever, wants, pb)
                finally:
                    self.target.commit_write_group()
            finally:
                self.target.unlock()
        finally:
            if create_pb:
                create_pb.finished()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return (isinstance(source, LocalGitRepository) and 
                target.supports_rich_root() and
                not isinstance(target, GitRepository))


class InterGitRepository(InterRepository):
    """InterRepository that copies between Git repositories."""

    _matching_repo_format = GitRepositoryFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        def progress(text):
            trace.info("git: %s", text)
        r = self.target._git
        if revision_id is not None:
            args = [mapping.revision_id_bzr_to_foreign(revision_id)[0]]
        elif fetch_spec is not None:
            args = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in fetch_spec.heads]
        if fetch_spec is None and revision_id is None:
            determine_wants = r.object_store.determine_wants_all
        else:
            determine_wants = lambda x: [y for y in args if not y in r.object_store]

        graphwalker = SimpleFetchGraphWalker(r.heads().values(), r.get_parents)
        f, commit = r.object_store.add_thin_pack()
        try:
            self.source.fetch_pack(determine_wants, graphwalker, f.write, progress)
            commit()
        except:
            f.close()
            raise

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, GitRepository) and 
                isinstance(target, GitRepository))
