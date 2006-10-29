# Copyright (C) 2005 Canonical Ltd
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



"""Text UI, write output to the console.
"""

import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import getpass

from bzrlib import (
    osutils,
    progress,
    )
""")

from bzrlib.symbol_versioning import (
    deprecated_method,
    zero_eight,
    )
from bzrlib.ui import CLIUIFactory


class TextUIFactory(CLIUIFactory):
    """A UI factory for Text user interefaces."""

    def __init__(self,
                 bar_type=None,
                 stdout=None,
                 stderr=None):
        """Create a TextUIFactory.

        :param bar_type: The type of progress bar to create. It defaults to 
                         letting the bzrlib.progress.ProgressBar factory auto
                         select.
        """
        super(TextUIFactory, self).__init__()
        self._bar_type = bar_type
        if stdout is None:
            self.stdout = sys.stdout
        else:
            self.stdout = stdout
        if stderr is None:
            self.stderr = sys.stderr
        else:
            self.stderr = stderr
        self._simple_progress_active = False

    def prompt(self, prompt):
        """Emit prompt on the CLI."""
        self.stdout.write(prompt + "? [y/n]:")
        
    @deprecated_method(zero_eight)
    def progress_bar(self):
        """See UIFactory.nested_progress_bar()."""
        # this in turn is abstract, and creates either a tty or dots
        # bar depending on what we think of the terminal
        return progress.ProgressBar()

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user 
                 canceled the request.
        """
        prompt = (prompt % kwargs).encode(sys.stdout.encoding, 'replace')
        prompt += ': '
        # There's currently no way to say 'i decline to enter a password'
        # as opposed to 'my password is empty' -- does it matter?
        return getpass.getpass(prompt)

    def nested_progress_bar(self):
        """Return a nested progress bar.
        
        The actual bar type returned depends on the progress module which
        may return a tty or dots bar depending on the terminal.
        """
        if self._progress_bar_stack is None:
            self._progress_bar_stack = progress.ProgressBarStack(
                klass=self._bar_type)
        return self._progress_bar_stack.get_nested()

    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position."""
        if self._simple_progress_active:
            self._clear_progress_line()
            return
        if self._progress_bar_stack is None:
            return
        overall_pb = self._progress_bar_stack.bottom()
        if overall_pb is not None:
            overall_pb.clear()

    def _clear_progress_line(self):
        if False:
            # erase it
            width = osutils.terminal_width() - 1
            self.stderr.write('\r')
            self.stderr.write(' ' * width)
            self.stderr.write('\r')
        else:
            # just leave it, and move to new line - more reliable and leaves
            # it there for context
            self.stderr.write('\n')
        self._simple_progress_active = False

    def show_progress_line(self, msg):
        width = osutils.terminal_width() - 1
        msg = msg[:width]
        msg = msg.ljust(width)
        self.stderr.write('\r' + msg)
        self.stderr.flush()
        self._simple_progress_active = True
    
    def message(self, msg):
        self.clear_term()
        self.stderr.write(msg + '\n')
