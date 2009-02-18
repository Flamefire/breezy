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

"""Import processor that supports all Bazaar repository formats."""


import os
import time
from bzrlib import (
    builtins,
    bzrdir,
    delta,
    errors,
    generate_ids,
    inventory,
    lru_cache,
    osutils,
    progress,
    revision,
    revisiontree,
    transport,
    )
from bzrlib.repofmt import pack_repo
from bzrlib.trace import note
import bzrlib.util.configobj.configobj as configobj
from bzrlib.plugins.fastimport import (
    branch_updater,
    cache_manager,
    errors as plugin_errors,
    helpers,
    idmapfile,
    marks_file,
    processor,
    revisionloader,
    )


# How many commits before automatically reporting progress
_DEFAULT_AUTO_PROGRESS = 1000

# How many commits before automatically checkpointing
_DEFAULT_AUTO_CHECKPOINT = 10000

# How many inventories to cache
_DEFAULT_INV_CACHE_SIZE = 10


class GenericProcessor(processor.ImportProcessor):
    """An import processor that handles basic imports.

    Current features supported:

    * blobs are cached in memory
    * files and symlinks commits are supported
    * checkpoints automatically happen at a configurable frequency
      over and above the stream requested checkpoints
    * timestamped progress reporting, both automatic and stream requested
    * some basic statistics are dumped on completion.

    At checkpoints and on completion, the commit-id -> revision-id map is
    saved to a file called 'fastimport-id-map'. If the import crashes
    or is interrupted, it can be started again and this file will be
    used to skip over already loaded revisions. The format of each line
    is "commit-id revision-id" so commit-ids cannot include spaces.

    Here are the supported parameters:

    * info - name of a hints file holding the analysis generated
      by running the fast-import-info processor in verbose mode. When
      importing large repositories, this parameter is needed so
      that the importer knows what blobs to intelligently cache.

    * trees - update the working trees before completing.
      By default, the importer updates the repository
      and branches and the user needs to run 'bzr update' for the
      branches of interest afterwards.

    * checkpoint - automatically checkpoint every n commits over and
      above any checkpoints contained in the import stream.
      The default is 10000.

    * count - only import this many commits then exit. If not set
      or negative, all commits are imported.
    
    * inv-cache - number of inventories to cache.
      If not set, the default is 10.

    * experimental - enable experimental mode, i.e. use features
      not yet fully tested.

    * import-marks - name of file to read to load mark information from

    * export-marks - name of file to write to save mark information to
    """

    known_params = [
        'info',
        'trees',
        'checkpoint',
        'count',
        'inv-cache',
        'experimental',
        'import-marks',
        'export-marks',
        ]

    def pre_process(self):
        self._start_time = time.time()
        self._load_info_and_params()
        self.cache_mgr = cache_manager.CacheManager(self.info, self.verbose,
            self.inventory_cache_size)
        
        if self.params.get("import-marks") is not None:
            mark_info = marks_file.import_marks(self.params.get("import-marks"))
            if mark_info is not None:
                self.cache_mgr.revision_ids = mark_info[0]
            self.skip_total = False
            self.first_incremental_commit = True
        else:
            self.first_incremental_commit = False
            self.skip_total = self._init_id_map()
            if self.skip_total:
                self.note("Found %d commits already loaded - "
                    "skipping over these ...", self.skip_total)
        self._revision_count = 0

        # mapping of tag name to revision_id
        self.tags = {}

        # Create the revision loader needed for committing
        new_repo_api = hasattr(self.repo, 'revisions')
        if new_repo_api:
            self.loader = revisionloader.RevisionLoader2(self.repo)
        elif not self._experimental:
            self.loader = revisionloader.RevisionLoader1(self.repo)
        else:
            def fulltext_when(count):
                total = self.total_commits
                if total is not None and count == total:
                    fulltext = True
                else:
                    # Create an inventory fulltext every 200 revisions
                    fulltext = count % 200 == 0
                if fulltext:
                    self.note("%d commits - storing inventory as full-text",
                        count)
                return fulltext

            self.loader = revisionloader.ImportRevisionLoader1(
                self.repo, self.inventory_cache_size,
                fulltext_when=fulltext_when)

        # Disable autopacking if the repo format supports it.
        # THIS IS A HACK - there is no sanctioned way of doing this yet.
        if isinstance(self.repo, pack_repo.KnitPackRepository):
            self._original_max_pack_count = \
                self.repo._pack_collection._max_pack_count
            def _max_pack_count_for_import(total_revisions):
                return total_revisions + 1
            self.repo._pack_collection._max_pack_count = \
                _max_pack_count_for_import
        else:
            self._original_max_pack_count = None
            
        # Create a write group. This is committed at the end of the import.
        # Checkpointing closes the current one and starts a new one.
        self.repo.start_write_group()

    def _load_info_and_params(self):
        self._experimental = bool(self.params.get('experimental', False))

        # This is currently hard-coded but might be configurable via
        # parameters one day if that's needed
        repo_transport = self.repo.control_files._transport
        self.id_map_path = repo_transport.local_abspath("fastimport-id-map")

        # Load the info file, if any
        info_path = self.params.get('info')
        if info_path is not None:
            self.info = configobj.ConfigObj(info_path)
        else:
            self.info = None

        # Decide how often to automatically report progress
        # (not a parameter yet)
        self.progress_every = _DEFAULT_AUTO_PROGRESS
        if self.verbose:
            self.progress_every = self.progress_every / 10

        # Decide how often to automatically checkpoint
        self.checkpoint_every = int(self.params.get('checkpoint',
            _DEFAULT_AUTO_CHECKPOINT))

        # Decide how big to make the inventory cache
        self.inventory_cache_size = int(self.params.get('inv-cache',
            _DEFAULT_INV_CACHE_SIZE))

        # Find the maximum number of commits to import (None means all)
        # and prepare progress reporting. Just in case the info file
        # has an outdated count of commits, we store the max counts
        # at which we need to terminate separately to the total used
        # for progress tracking.
        try:
            self.max_commits = int(self.params['count'])
            if self.max_commits < 0:
                self.max_commits = None
        except KeyError:
            self.max_commits = None
        if self.info is not None:
            self.total_commits = int(self.info['Command counts']['commit'])
            if (self.max_commits is not None and
                self.total_commits > self.max_commits):
                self.total_commits = self.max_commits
        else:
            self.total_commits = self.max_commits

    def _process(self, command_iter):
        # if anything goes wrong, abort the write group if any
        try:
            processor.ImportProcessor._process(self, command_iter)
        except:
            if self.repo is not None and self.repo.is_in_write_group():
                self.repo.abort_write_group()
            raise

    def post_process(self):
        # Commit the current write group and checkpoint the id map
        self.repo.commit_write_group()
        self._save_id_map()

        if self.params.get("export-marks") is not None:
            marks_file.export_marks(self.params.get("export-marks"),
                self.cache_mgr.revision_ids)

        # Update the branches
        self.note("Updating branch information ...")
        updater = branch_updater.BranchUpdater(self.repo, self.branch,
            self.cache_mgr, helpers.invert_dictset(self.cache_mgr.heads),
            self.cache_mgr.last_ref, self.tags)
        branches_updated, branches_lost = updater.update()
        self._branch_count = len(branches_updated)

        # Tell the user about branches that were not created
        if branches_lost:
            if not self.repo.is_shared():
                self.warning("Cannot import multiple branches into "
                    "an unshared repository")
            self.warning("Not creating branches for these head revisions:")
            for lost_info in branches_lost:
                head_revision = lost_info[1]
                branch_name = lost_info[0]
                self.note("\t %s = %s", head_revision, branch_name)

        # Update the working trees as requested and dump stats
        self._tree_count = 0
        remind_about_update = True
        if self._branch_count == 0:
            self.note("no branches to update")
            self.note("no working trees to update")
            remind_about_update = False
        elif self.params.get('trees', False):
            trees = self._get_working_trees(branches_updated)
            if trees:
                self.note("Updating the working trees ...")
                if self.verbose:
                    report = delta._ChangeReporter()
                else:
                    reporter = None
                for wt in trees:
                    wt.update(reporter)
                    self._tree_count += 1
                remind_about_update = False
            else:
                self.warning("No working trees available to update")
        self.dump_stats()

        # Finish up by telling the user what to do next.
        if self._original_max_pack_count:
            # We earlier disabled autopacking, creating one pack every
            # checkpoint instead. We now pack the repository to optimise
            # how data is stored.
            if self._revision_count > self.checkpoint_every:
                self.note("Packing repository ...")
                self.repo.pack()
                # To be conservative, packing puts the old packs and
                # indices in obsolete_packs. We err on the side of
                # optimism and clear out that directory to save space.
                self.note("Removing obsolete packs ...")
                # TODO: Use a public API for this once one exists
                repo_transport = self.repo._pack_collection.transport
                repo_transport.clone('obsolete_packs').delete_multi(
                    repo_transport.list_dir('obsolete_packs'))
        if remind_about_update:
            # This message is explicitly not timestamped.
            note("To refresh the working tree for a branch, "
                "use 'bzr update'.")

    def _get_working_trees(self, branches):
        """Get the working trees for branches in the repository."""
        result = []
        wt_expected = self.repo.make_working_trees()
        for br in branches:
            if br == self.branch and br is not None:
                wt = self.working_tree
            elif wt_expected:
                try:
                    wt = br.bzrdir.open_workingtree()
                except errors.NoWorkingTree:
                    self.warning("No working tree for branch %s", br)
                    continue
            else:
                continue
            result.append(wt)
        return result

    def dump_stats(self):
        time_required = progress.str_tdelta(time.time() - self._start_time)
        rc = self._revision_count - self.skip_total
        bc = self._branch_count
        wtc = self._tree_count
        self.note("Imported %d %s, updating %d %s and %d %s in %s",
            rc, helpers.single_plural(rc, "revision", "revisions"),
            bc, helpers.single_plural(bc, "branch", "branches"),
            wtc, helpers.single_plural(wtc, "tree", "trees"),
            time_required)

    def _init_id_map(self):
        """Load the id-map and check it matches the repository.
        
        :return: the number of entries in the map
        """
        # Currently, we just check the size. In the future, we might
        # decide to be more paranoid and check that the revision-ids
        # are identical as well.
        self.cache_mgr.revision_ids, known = idmapfile.load_id_map(
            self.id_map_path)
        existing_count = len(self.repo.all_revision_ids())
        if existing_count < known:
            raise plugin_errors.BadRepositorySize(known, existing_count)
        return known

    def _save_id_map(self):
        """Save the id-map."""
        # Save the whole lot every time. If this proves a problem, we can
        # change to 'append just the new ones' at a later time.
        idmapfile.save_id_map(self.id_map_path, self.cache_mgr.revision_ids)

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        if cmd.mark is not None:
            dataref = cmd.id
        else:
            dataref = osutils.sha_strings(cmd.data)
        self.cache_mgr.store_blob(dataref, cmd.data)

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        # Commit the current write group and start a new one
        self.repo.commit_write_group()
        self._save_id_map()
        self.repo.start_write_group()

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        if self.skip_total and self._revision_count < self.skip_total:
            _track_heads(cmd, self.cache_mgr)
            # Check that we really do know about this commit-id
            if not self.cache_mgr.revision_ids.has_key(cmd.id):
                raise plugin_errors.BadRestart(cmd.id)
            # Consume the file commands and free any non-sticky blobs
            for fc in cmd.file_iter():
                pass
            self.cache_mgr._blobs = {}
            self._revision_count += 1
            # If we're finished getting back to where we were,
            # load the file-ids cache
            if self._revision_count == self.skip_total:
                self._gen_file_ids_cache()
                self.note("Generated the file-ids cache - %d entries",
                    len(self.cache_mgr.file_ids.keys()))
            return
        if self.first_incremental_commit:
            self.first_incremental_commit = None
            parents = _track_heads(cmd, self.cache_mgr)
            self._gen_file_ids_cache(parents)

        # 'Commit' the revision and report progress
        handler = GenericCommitHandler(cmd, self.repo, self.cache_mgr,
            self.loader, self.verbose, self._experimental)
        handler.process()
        self.cache_mgr.revision_ids[cmd.id] = handler.revision_id
        self._revision_count += 1
        self.report_progress("(%s)" % cmd.id)

        # Check if we should finish up or automatically checkpoint
        if (self.max_commits is not None and
            self._revision_count >= self.max_commits):
            self.note("Stopping after reaching requested count of commits")
            self.finished = True
        elif self._revision_count % self.checkpoint_every == 0:
            self.note("%d commits - automatic checkpoint triggered",
                self._revision_count)
            self.checkpoint_handler(None)

    def _gen_file_ids_cache(self, revs=False):
        """Generate the file-id cache by searching repository inventories.
        """
        # Get the interesting revisions - the heads
        if revs:
            head_ids = revs
        else:
            head_ids = self.cache_mgr.heads.keys()
        revision_ids = [self.cache_mgr.revision_ids[h] for h in head_ids]

        # Update the fileid cache
        file_ids = {}
        for revision_id in revision_ids:
            inv = self.repo.revision_tree(revision_id).inventory
            # Cache the inventories while we're at it
            self.cache_mgr.inventories[revision_id] = inv
            for path, ie in inv.iter_entries():
                file_ids[path] = ie.file_id
        self.cache_mgr.file_ids = file_ids

    def report_progress(self, details=''):
        # TODO: use a progress bar with ETA enabled
        if self._revision_count % self.progress_every == 0:
            if self.total_commits is not None:
                counts = "%d/%d" % (self._revision_count, self.total_commits)
                eta = progress.get_eta(self._start_time, self._revision_count,
                    self.total_commits)
                eta_str = progress.str_tdelta(eta)
                if eta_str.endswith('--'):
                    eta_str = ''
                else:
                    eta_str = '[%s] ' % eta_str
            else:
                counts = "%d" % (self._revision_count,)
                eta_str = ''
            self.note("%s commits processed %s%s" % (counts, eta_str, details))

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # We could use a progress bar here instead
        self.note("progress %s" % (cmd.message,))

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.ref.startswith('refs/tags/'):
            tag_name = cmd.ref[len('refs/tags/'):]
            if cmd.from_ is not None:
                self._set_tag(tag_name, cmd.from_)
            elif self.verbose:
                self.warning("ignoring reset refs/tags/%s - no from clause"
                    % tag_name)
            return

	# FIXME: cmd.from_ is a committish and thus could reference
	# another branch.  Create a method for resolving commitish's.
        if cmd.from_ is not None:
            self.cache_mgr.track_heads_for_ref(cmd.ref, cmd.from_)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        if cmd.from_ is not None:
            self._set_tag(cmd.id, cmd.from_)
        else:
            self.warning("ignoring tag %s - no from clause" % cmd.id)

    def _set_tag(self, name, from_):
        """Define a tag given a name and import 'from' reference."""
        bzr_tag_name = name.decode('utf-8', 'replace')
        bzr_rev_id = self.cache_mgr.revision_ids[from_]
        self.tags[bzr_tag_name] = bzr_rev_id


def _track_heads(cmd, cache_mgr):
    """Track the repository heads given a CommitCommand.
    
    :return: the list of parents in terms of commit-ids
    """
    # Get the true set of parents
    if cmd.from_ is not None:
        parents = [cmd.from_]
    else:
        last_id = cache_mgr.last_ids.get(cmd.ref)
        if last_id is not None:
            parents = [last_id]
        else:
            parents = []
    parents.extend(cmd.merges)

    # Track the heads
    cache_mgr.track_heads_for_ref(cmd.ref, cmd.id, parents)
    return parents


class GenericCommitHandler(processor.CommitHandler):

    def __init__(self, command, repo, cache_mgr, loader, verbose=False,
        _experimental=False):
        processor.CommitHandler.__init__(self, command)
        self.repo = repo
        self.cache_mgr = cache_mgr
        self.loader = loader
        self.verbose = verbose
        self._experimental = _experimental

    def pre_process_files(self):
        """Prepare for committing."""
        self.revision_id = self.gen_revision_id()
        # cache of texts for this commit, indexed by file-id
        self.lines_for_commit = {}
        if self.repo.supports_rich_root():
            self.lines_for_commit[inventory.ROOT_ID] = []

        # Track the heads and get the real parent list
        parents = _track_heads(self.command, self.cache_mgr)

        # Convert the parent commit-ids to bzr revision-ids
        if parents:
            self.parents = [self.cache_mgr.revision_ids[p]
                for p in parents]
        else:
            self.parents = []
        self.debug("%s id: %s, parents: %s", self.command.id,
            self.revision_id, str(self.parents))

        # Seed the inventory from the previous one
        if len(self.parents) == 0:
            self.inventory = self.gen_initial_inventory()
        else:
            # use the bzr_revision_id to lookup the inv cache
            inv = self.get_inventory(self.parents[0])
            # TODO: Shallow copy - deep inventory copying is expensive
            self.inventory = inv.copy()
        if self.repo.supports_rich_root():
            self.inventory.revision_id = self.revision_id
        else:
            # In this repository, root entries have no knit or weave. When
            # serializing out to disk and back in, root.revision is always
            # the new revision_id.
            self.inventory.root.revision = self.revision_id

        # directory-path -> inventory-entry for current inventory
        self.directory_entries = dict(self.inventory.directories())

    def post_process_files(self):
        """Save the revision."""
        self.cache_mgr.inventories[self.revision_id] = self.inventory

        # Load the revision into the repository
        rev_props = {}
        committer = self.command.committer
        who = "%s <%s>" % (committer[0],committer[1])
        author = self.command.author
        if author is not None:
            author_id = "%s <%s>" % (author[0],author[1])
            if author_id != who:
                rev_props['author'] = author_id
        rev = revision.Revision(
           timestamp=committer[2],
           timezone=committer[3],
           committer=who,
           message=helpers.escape_commit_message(self.command.message),
           revision_id=self.revision_id,
           properties=rev_props,
           parent_ids=self.parents)
        self.loader.load(rev, self.inventory, None,
            lambda file_id: self._get_lines(file_id),
            lambda revision_ids: self._get_inventories(revision_ids))

    def modify_handler(self, filecmd):
        if filecmd.dataref is not None:
            data = self.cache_mgr.fetch_blob(filecmd.dataref)
        else:
            data = filecmd.data
        self.debug("modifying %s", filecmd.path)
        self._modify_inventory(filecmd.path, filecmd.kind,
            filecmd.is_executable, data)

    def _delete_recursive(self, path):
        self.debug("deleting %s", path)
        fileid = self.bzr_file_id(path)
        dirname, basename = osutils.split(path)
        if (fileid in self.inventory and
            isinstance(self.inventory[fileid], inventory.InventoryDirectory)):
            for child_path in self.inventory[fileid].children.keys():
                self._delete_recursive(os.utils.pathjoin(path, child_path))
        try:
            if self.inventory.id2path(fileid) == path:
                del self.inventory[fileid]
            else:
                # already added by some other name?
                if dirname in self.cache_mgr.file_ids:
                    parent_id = self.cache_mgr.file_ids[dirname]
                    del self.inventory[parent_id].children[basename]
        except KeyError:
            self._warn_unless_in_merges(fileid, path)
        except errors.NoSuchId:
            self._warn_unless_in_merges(fileid, path)
        except AttributeError, ex:
            if ex.args[0] == 'children':
                # A directory has changed into a file and then one
                # of it's children is being deleted!
                self._warn_unless_in_merges(fileid, path)
            else:
                raise
        try:
            self.cache_mgr.delete_path(path)
        except KeyError:
            pass

    def delete_handler(self, filecmd):
        self._delete_recursive(filecmd.path)

    def _warn_unless_in_merges(self, fileid, path):
        if len(self.parents) <= 1:
            return
        for parent in self.parents[1:]:
            if fileid in self.get_inventory(parent):
                return
        self.warning("ignoring delete of %s as not in parent inventories", path)

    def copy_handler(self, filecmd):
        src_path = filecmd.src_path
        dest_path = filecmd.dest_path
        self.debug("copying %s to %s", src_path, dest_path)
        if not self.parents:
            self.warning("ignoring copy of %s to %s - no parent revisions",
                src_path, dest_path)
            return
        file_id = self.inventory.path2id(src_path)
        if file_id is None:
            self.warning("ignoring copy of %s to %s - source does not exist",
                src_path, dest_path)
            return
        ie = self.inventory[file_id]
        kind = ie.kind
        if kind == 'file':
            content = self._get_content_from_repo(self.parents[0], file_id)
            self._modify_inventory(dest_path, kind, ie.executable, content)
        elif kind == 'symlink':
            self._modify_inventory(dest_path, kind, False, ie.symlink_target)
        else:
            self.warning("ignoring copy of %s %s - feature not yet supported",
                kind, path)

    def _get_content_from_repo(self, revision_id, file_id):
        """Get the content of a file for a revision-id."""
        revtree = self.repo.revision_tree(revision_id)
        return revtree.get_file_text(file_id)

    def rename_handler(self, filecmd):
        old_path = filecmd.old_path
        new_path = filecmd.new_path
        self.debug("renaming %s to %s", old_path, new_path)
        file_id = self.bzr_file_id(old_path)
        basename, new_parent_ie = self._ensure_directory(new_path)
        new_parent_id = new_parent_ie.file_id
        existing_id = self.inventory.path2id(new_path)
        if existing_id is not None:
            self.inventory.remove_recursive_id(existing_id)
        ie = self.inventory[file_id]
        lines = self.loader._get_lines(file_id, ie.revision)
        self.lines_for_commit[file_id] = lines
        self.inventory.rename(file_id, new_parent_id, basename)
        self.cache_mgr.rename_path(old_path, new_path)
        self.inventory[file_id].revision = self.revision_id

    def deleteall_handler(self, filecmd):
        self.debug("deleting all files (and also all directories)")
        # Would be nice to have an inventory.clear() method here
        root_items = [ie for (name, ie) in
            self.inventory.root.children.iteritems()]
        for root_item in root_items:
            self.inventory.remove_recursive_id(root_item.file_id)

    def bzr_file_id_and_new(self, path):
        """Get a Bazaar file identifier and new flag for a path.
        
        :return: file_id, is_new where
          is_new = True if the file_id is newly created
        """
        try:
            id = self.cache_mgr.file_ids[path]
            return id, False
        except KeyError:
            id = generate_ids.gen_file_id(path)
            self.cache_mgr.file_ids[path] = id
            self.debug("Generated new file id %s for '%s'", id, path)
            return id, True

    def bzr_file_id(self, path):
        """Get a Bazaar file identifier for a path."""
        return self.bzr_file_id_and_new(path)[0]

    def gen_initial_inventory(self):
        """Generate an inventory for a parentless revision."""
        inv = inventory.Inventory(revision_id=self.revision_id)
        if self.repo.supports_rich_root():
            # The very first root needs to have the right revision
            inv.root.revision = self.revision_id
        return inv

    def gen_revision_id(self):
        """Generate a revision id.

        Subclasses may override this to produce deterministic ids say.
        """
        committer = self.command.committer
        # Perhaps 'who' being the person running the import is ok? If so,
        # it might be a bit quicker and give slightly better compression?
        who = "%s <%s>" % (committer[0],committer[1])
        timestamp = committer[2]
        return generate_ids.gen_revision_id(who, timestamp)

    def get_inventory(self, revision_id):
        """Get the inventory for a revision id."""
        try:
            inv = self.cache_mgr.inventories[revision_id]
        except KeyError:
            if self.verbose:
                self.note("get_inventory cache miss for %s", revision_id)
            # Not cached so reconstruct from repository
            inv = self.repo.revision_tree(revision_id).inventory
            self.cache_mgr.inventories[revision_id] = inv
        return inv

    def _get_inventories(self, revision_ids):
        """Get the inventories for revision-ids.
        
        This is a callback used by the RepositoryLoader to
        speed up inventory reconstruction.
        """
        present = []
        inventories = []
        # If an inventory is in the cache, we assume it was
        # successfully loaded into the repsoitory
        for revision_id in revision_ids:
            try:
                inv = self.cache_mgr.inventories[revision_id]
                present.append(revision_id)
            except KeyError:
                if self.verbose:
                    self.note("get_inventories cache miss for %s", revision_id)
                # Not cached so reconstruct from repository
                if self.repo.has_revision(revision_id):
                    rev_tree = self.repo.revision_tree(revision_id)
                    present.append(revision_id)
                else:
                    rev_tree = self.repo.revision_tree(None)
                inv = rev_tree.inventory
                self.cache_mgr.inventories[revision_id] = inv
            inventories.append(inv)
        return present, inventories

    def _get_lines(self, file_id):
        """Get the lines for a file-id."""
        return self.lines_for_commit[file_id]

    def _modify_inventory(self, path, kind, is_executable, data):
        """Add to or change an item in the inventory."""
        # Create the new InventoryEntry
        basename, parent_ie = self._ensure_directory(path)
        file_id = self.bzr_file_id(path)
        ie = inventory.make_entry(kind, basename, parent_ie.file_id, file_id)
        ie.revision = self.revision_id
        if isinstance(ie, inventory.InventoryFile):
            ie.executable = is_executable
            lines = osutils.split_lines(data)
            ie.text_sha1 = osutils.sha_strings(lines)
            ie.text_size = sum(map(len, lines))
            self.lines_for_commit[file_id] = lines
        elif isinstance(ie, inventory.InventoryLink):
            ie.symlink_target = data.encode('utf8')
            # There are no lines stored for a symlink so
            # make sure the cache used by get_lines knows that
            self.lines_for_commit[file_id] = []
        else:
            raise errors.BzrError("Cannot import items of kind '%s' yet" %
                (kind,))

        # Record this new inventory entry
        if file_id in self.inventory:
            # HACK: no API for this (del+add does more than it needs to)
            self.inventory._byid[file_id] = ie
            parent_ie.children[basename] = ie
        else:
            self.inventory.add(ie)

    def _ensure_directory(self, path):
        """Ensure that the containing directory exists for 'path'"""
        dirname, basename = osutils.split(path)
        if dirname == '':
            # the root node doesn't get updated
            return basename, self.inventory.root
        try:
            ie = self.directory_entries[dirname]
        except KeyError:
            # We will create this entry, since it doesn't exist
            pass
        else:
            return basename, ie

        # No directory existed, we will just create one, first, make sure
        # the parent exists
        dir_basename, parent_ie = self._ensure_directory(dirname)
        dir_file_id = self.bzr_file_id(dirname)
        ie = inventory.entry_factory['directory'](dir_file_id,
                                                  dir_basename,
                                                  parent_ie.file_id)
        ie.revision = self.revision_id
        self.directory_entries[dirname] = ie
        # There are no lines stored for a directory so
        # make sure the cache used by get_lines knows that
        self.lines_for_commit[dir_file_id] = []
        #print "adding dir for %s" % path
        self.inventory.add(ie)
        return basename, ie
