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

"""Logic to create commit templates."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import osutils, patiencediff
""")

class CommitTemplate(object):

    def __init__(self, commit, message):
        """Create a commit template for commit with initial message message.

        :param commit: A Commit object for the in progress commit.
        :param message: The current message (which may be None).
        """
        self.commit = commit
        self.message = message

    def make(self):
        """Make the template.

        If NEWS is missing or not not modified, the original template is
        returned unaltered. Otherwise the changes from NEWS are concatenated
        with whatever message was provided to __init__.
        """
        try:
            delta = self.commit.builder.get_basis_delta()
        except AssertionError:
            # Not 2a, someone can write a slow-format code path if they want
            # to.
            return self.messsage
        found_old_path = None
        found_entry = None
        for old_path, new_path, fileid, entry in delta:
            if new_path == 'NEWS':
                found_entry = entry
                found_old_path = old_path
                break
        if not found_entry:
            return self.message
        if found_old_path is None:
            # New file
            _, new_chunks = list(self.commit.builder.repository.iter_files_bytes(
                [(found_entry.file_id, found_entry.revision, None)]))[0]
            content = ''.join(new_chunks)
            return self.merge_message(content)
        else:
            # Get a diff. XXX Is this hookable? I thought it was, can't find it
            # though.... add DiffTree.diff_factories. Sadly thats not at the 
            # right level: we want to identify the changed lines, not have the
            # final diff: because we want to grab the sections for regions 
            # changed in new version of the file. So for now a direct diff
            # using patiencediff is done.
            old_entry = self.commit.basis_tree.inventory[found_entry.file_id]
            needed = [(found_entry.file_id, found_entry.revision, 'new'),
                (old_entry.file_id, old_entry.revision, 'old')]
            contents = self.commit.builder.repository.iter_files_bytes(needed)
            lines = {}
            for name, chunks in contents:
                lines[name] = osutils.chunks_to_lines(chunks)
            new = lines['new']
            sequence_matcher = patiencediff.PatienceSequenceMatcher(
                None, lines['old'], new)
            new_lines = []
            for group in sequence_matcher.get_opcodes():
                tag, i1, i2, j1, j2 = group
                if tag == 'equal':
                    continue
                if tag == 'delete':
                    continue
                new_lines.extend(new[j1:j2])
            return ''.join(new_lines)

    def merge_message(self, new_message):
        """Merge new_message with self.message.
        
        :param new_message: A string message to merge with self.message.
        :return: A string with the merged messages.
        """
        if self.message is None:
            return new_message
        return self.message + new_message
