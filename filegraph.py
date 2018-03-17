# Copyright (C) 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""File graph access."""

from __future__ import absolute_import

import stat

from dulwich.errors import (
    NotTreeError,
    )
from dulwich.object_store import (
    tree_lookup_path,
    )

from ...revision import (
    NULL_REVISION,
    )


class GitFileLastChangeScanner(object):

    def __init__(self, repository):
        self.repository = repository
        self.store = self.repository._git.object_store

    def find_last_change_revision(self, path, commit_id):
        commit = self.store[commit_id]
        target_mode, target_sha = tree_lookup_path(self.store.__getitem__,
            commit.tree, path)
        if path == '':
            target_mode = stat.S_IFDIR | 0644
        assert target_mode is not None, "sha %r for %r in %r" % (target_sha, path, commit_id)
        while True:
            parent_commits = []
            for parent_commit in [self.store[c] for c in commit.parents]:
                try:
                    mode, sha = tree_lookup_path(self.store.__getitem__,
                        parent_commit.tree, path)
                except (NotTreeError, KeyError):
                    continue
                else:
                    parent_commits.append(parent_commit)
                if path == '':
                    mode = stat.S_IFDIR | 0644
                # Candidate found iff, mode or text changed,
                # or is a directory that didn't previously exist.
                if mode != target_mode or (
                    not stat.S_ISDIR(target_mode) and sha != target_sha):
                        return (path, commit.id)
            if parent_commits == []:
                break
            commit = parent_commits[0]
        return (path, commit.id)


class GitFileParentProvider(object):

    def __init__(self, change_scanner):
        self.change_scanner = change_scanner
        self.store = self.change_scanner.repository._git.object_store

    def _get_parents(self, file_id, text_revision):
        commit_id, mapping = self.change_scanner.repository.lookup_bzr_revision_id(
            text_revision)
        try:
            path = mapping.parse_file_id(file_id)
        except ValueError:
            raise KeyError(file_id)
        text_parents = []
        for commit_parent in self.store[commit_id].parents:
            try:
                (path, text_parent) = self.change_scanner.find_last_change_revision(path, commit_parent)
            except KeyError:
                continue
            if text_parent not in text_parents:
                text_parents.append(text_parent)
        return tuple([(file_id,
            self.change_scanner.repository.lookup_foreign_revision_id(p)) for p
            in text_parents])

    def get_parent_map(self, keys):
        ret = {}
        for key in keys:
            (file_id, text_revision) = key
            if text_revision == NULL_REVISION:
                ret[key] = ()
                continue
            try:
                ret[key] = self._get_parents(file_id, text_revision)
            except KeyError:
                pass
        return ret
