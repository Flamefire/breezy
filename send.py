# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# Based on the original from bzr-svn:
# Copyright (C) 2009 Lukas Lalinsky <lalinsky@gmail.com>
# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Support in "bzr send" for git-am style patches."""

import time
import bzrlib
from bzrlib import (
    branch as _mod_branch,
    diff as _mod_diff,
    merge_directive,
    osutils,
    revision as _mod_revision,
    )

from bzrlib.plugins.git import (
    version_info as bzr_git_version_info,
    )
from bzrlib.plugins.git.mapping import (
    object_mode,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store,
    )

from cStringIO import StringIO
from dulwich import (
    __version__ as dulwich_version,
    )
from dulwich.objects import (
    Blob,
    )


version_tail = "bzr %s, bzr-git %d.%d.%d, dulwich %d.%d.%d" % (
    (bzrlib.__version__, ) + bzr_git_version_info[:3] + dulwich_version[:3])


class GitDiffTree(_mod_diff.DiffTree):
    """Provides a text representation between two trees, formatted for svn."""

    def _show_diff(self, specific_files, extra_trees):
        from dulwich.patch import write_blob_diff
        iterator = self.new_tree.iter_changes(self.old_tree,
            specific_files=specific_files, extra_trees=extra_trees,
            require_versioned=True)
        has_changes = 0
        def get_encoded_path(path):
            if path is not None:
                return path.encode(self.path_encoding, "replace")
        def get_file_mode(tree, path, kind, executable):
            if path is None:
                return None
            return object_mode(kind, executable)
        def get_blob(present, tree, file_id):
            if present is not None:
                return Blob.from_string(tree.get_file(file_id).read())
            else:
                return None
        trees = (self.old_tree, self.new_tree)
        for (file_id, paths, changed_content, versioned, parent, name, kind,
             executable) in iterator:
            # The root does not get diffed, and items with no known kind (that
            # is, missing) in both trees are skipped as well.
            if parent == (None, None) or kind == (None, None):
                continue
            path_encoded = (get_encoded_path(paths[0]), 
                            get_encoded_path(paths[1]))
            present = ((kind[0] is not None and versioned[0]),
                       (kind[1] is not None and versioned[1]))
            contents = (get_blob(present[0], trees[0], file_id),
                        get_blob(present[1], trees[1], file_id))
            renamed = (parent[0], name[0]) != (parent[1], name[1])
            mode = (get_file_mode(trees[0], path_encoded[0], 
                                  kind[0], executable[0]), 
                    get_file_mode(trees[1], path_encoded[1], 
                                  kind[1], executable[1]))
            write_blob_diff(self.to_file, 
                (path_encoded[0], mode[0], contents[0]), 
                (path_encoded[1], mode[1], contents[1]))
            has_changes |= (changed_content or renamed)
        return has_changes


class GitMergeDirective(merge_directive._BaseMergeDirective):

    def to_lines(self):
        return self.patch.splitlines(True)

    @classmethod
    def _generate_commit(cls, repository, revision_id, num, total):
        s = StringIO()
        store = get_object_store(repository)
        commit = store[store._lookup_revision_sha1(revision_id)]
        from dulwich.patch import write_commit_patch, get_summary
        try:
            lhs_parent = repository.get_revision(revision_id).parent_ids[0]
        except IndexError:
            lhs_parent = _mod_revision.NULL_REVISION
        tree_1 = repository.revision_tree(lhs_parent)
        tree_2 = repository.revision_tree(revision_id)
        contents = StringIO()
        differ = GitDiffTree.from_trees_options(tree_1, tree_2, 
                contents, 'utf8', None, 'a/', 'b/', None)
        differ.show_diff(None, None)
        write_commit_patch(s, commit, contents.getvalue(), (num, total), 
                           version_tail)
        summary = "%04d-%s" % (num, get_summary(commit))
        return summary, s.getvalue()

    @classmethod
    def from_objects(cls, repository, revision_id, time, timezone,
                     target_branch, local_target_branch=None,
                     public_branch=None, message=None):
        patches = []
        submit_branch = _mod_branch.Branch.open(target_branch)
        submit_branch.lock_read()
        try:
            submit_revision_id = submit_branch.last_revision()
            repository.fetch(submit_branch.repository, submit_revision_id)
            graph = repository.get_graph()
            todo = graph.find_difference(submit_revision_id, revision_id)[1]
            total = len(todo)
            for i, revid in enumerate(graph.iter_topo_order(todo)):
                patches.append(cls._generate_commit(repository, revid, i+1, 
                                                    total))
        finally:
            submit_branch.unlock()
        return cls(revision_id, None, time, timezone, target_branch, 
            "".join([patch for (summary, patch) in patches]), 
            None, public_branch, message)


def send_git(branch, revision_id, submit_branch, public_branch,
              no_patch, no_bundle, message, base_revision_id):
    return GitMergeDirective.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, message=message)
