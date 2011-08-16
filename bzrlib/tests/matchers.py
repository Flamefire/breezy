# Copyright (C) 2010 Canonical Ltd
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

"""Matchers for bzrlib.

Primarily test support, Matchers are used by self.assertThat in the bzrlib
test suite. A matcher is a stateful test helper which can be used to determine
if a passed object 'matches', much like a regex. If the object does not match
the mismatch can be described in a human readable fashion. assertThat then
raises if a mismatch occurs, showing the description as the assertion error.

Matchers are designed to be more reusable and composable than layered
assertions in Test Case objects, so they are recommended for new testing work.
"""

__all__ = [
    'MatchesAncestry',
    'ReturnsUnlockable',
    ]

from bzrlib import (
    revision as _mod_revision,
    )

from testtools.matchers import Equals, Mismatch, Matcher


class ReturnsUnlockable(Matcher):
    """A matcher that checks for the pattern we want lock* methods to have:

    They should return an object with an unlock() method.
    Calling that method should unlock the original object.

    :ivar lockable_thing: The object which can be locked that will be
        inspected.
    """

    def __init__(self, lockable_thing):
        Matcher.__init__(self)
        self.lockable_thing = lockable_thing

    def __str__(self):
        return ('ReturnsUnlockable(lockable_thing=%s)' % 
            self.lockable_thing)

    def match(self, lock_method):
        lock_method().unlock()
        if self.lockable_thing.is_locked():
            return _IsLocked(self.lockable_thing)
        return None


class _IsLocked(Mismatch):
    """Something is locked."""

    def __init__(self, lockable_thing):
        self.lockable_thing = lockable_thing

    def describe(self):
        return "%s is locked" % self.lockable_thing


class _AncestryMismatch(Mismatch):
    """Ancestry matching mismatch."""

    def __init__(self, tip_revision, got, expected):
        self.tip_revision = tip_revision
        self.got = got
        self.expected = expected

    def describe(self):
        return "mismatched ancestry for revision %r was %r, expected %r" % (
            self.tip_revision, self.got, self.expected)


class MatchesAncestry(Matcher):
    """A matcher that checks the ancestry of a particular revision.

    :ivar graph: Graph in which to check the ancestry
    :ivar revision_id: Revision id of the revision
    """

    def __init__(self, repository, revision_id):
        Matcher.__init__(self)
        self.repository = repository
        self.revision_id = revision_id

    def __str__(self):
        return ('MatchesAncestry(repository=%r, revision_id=%r)' % (
            self.repository, self.revision_id))

    def match(self, expected):
        self.repository.lock_read()
        try:
            graph = self.repository.get_graph()
            got = [r for r, p in graph.iter_ancestry([self.revision_id])]
            if _mod_revision.NULL_REVISION in got:
                got.remove(_mod_revision.NULL_REVISION)
        finally:
            self.repository.unlock()
        if sorted(got) != sorted(expected):
            return _AncestryMismatch(self.revision_id, sorted(got),
                sorted(expected))


class HasLayout(Matcher):
    """A matcher that checks if a tree has a specific layout.

    :ivar entries: List of expected entries, as (path, file_id) pairs.
    """

    def __init__(self, entries):
        Matcher.__init__(self)
        self.entries = entries

    def get_tree_layout(self, tree):
        """Get the (path, file_id) pairs for the current tree."""
        tree.lock_read()
        try:
            return [(path, ie.file_id) for path, ie
                    in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()

    def __str__(self):
        return ('HasLayout(%r)' % self.entries)

    def match(self, tree):
        actual = self.get_tree_layout(tree)
        if self.entries and isinstance(self.entries[0], basestring):
            actual = [path for (path, fileid) in actual]
        return Equals(actual).match(self.entries)
