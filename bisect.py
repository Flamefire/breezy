# bisect plugin for Bazaar 2.x (bzr)
# Copyright 2006 Jeff Licquia.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import os
import bzrlib.bzrdir
import bzrlib.tests
from bzrlib.commands import Command, register_command
from bzrlib.errors import BzrCommandError
from bzrlib.option import Option

bisect_info_path = ".bzr/bisect"
bisect_rev_path = ".bzr/bisect_revid"

class BisectCurrent(object):
    "Bisect class for managing the current revision."

    def __init__(self, filename = bisect_rev_path):
        self._filename = filename
        self._bzrdir = bzrlib.bzrdir.BzrDir.open_containing(".")[0]
        self._bzrbranch = self._bzrdir.open_branch()
        if os.path.exists(filename):
            f = open(filename)
            self._revid = f.read().strip()
            f.close()
        else:
            self._revid = self._bzrbranch.last_revision()

    def _save(self):
        f = open(self._filename, "w")
        f.write(self._revid + "\n")
        f.close()

    def get_current_revid(self):
        return self._revid

    def show_rev_log(self, out = sys.stdout):
        from bzrlib.log import ShortLogFormatter, show_log
        lf = ShortLogFormatter(out, show_ids = True)
        revno = self._bzrbranch.revision_id_to_revno(self._revid)
        show_log(self._bzrbranch, lf,
                 start_revision = revno, end_revision = revno)

    def switch(self, revid):
        wt = self._bzrdir.open_workingtree()
        if isinstance(revid, int):
            revid = self._bzrbranch.get_rev_id(revid)
        elif isinstance(revid, list):
            revid = revid[0].in_history(wt.branch).rev_id
        wt.revert([], wt.branch.repository.revision_tree(revid), False)
        self._revid = revid
        self._save()

    def reset(self):
        wt = self._bzrdir.open_workingtree()
        last_rev = wt.branch.last_revision()
        rev_tree = wt.branch.repository.revision_tree(last_rev)
        wt.revert([], rev_tree, False)
        if os.path.exists(bisect_rev_path):
            os.unlink(bisect_rev_path)

class BisectLog(object):
    "Bisect log file handler."

    def __init__(self, filename = bisect_info_path):
        self._items = []
        self._current = BisectCurrent()
        self._bzrdir = None
        self._low_revno = None
        self._middle_revno = None
        self.change_file_name(filename)
        self.load()

    def _open_for_read(self):
        if self._filename:
            return open(self._filename)
        else:
            return sys.stdin

    def _open_for_write(self):
        if self._filename:
            return open(self._filename, "w")
        else:
            return sys.stdout

    def _load_bzr_tree(self):
        if not self._bzrdir:
            self._bzrdir = bzrlib.bzrdir.BzrDir.open_containing('.')[0]
            self._bzrbranch = self._bzrdir.open_branch()

    def _find_current_range(self):
        self._load_bzr_tree()

        self._high_revno = None
        self._low_revno = None
        self._middle_revno = None
        revno = 1
        for revision in self._bzrbranch.revision_history():
            matches = [x[1] for x in self._items 
                       if x[0] == revision and x[1] in ('yes', 'no')]
            if not matches:
                revno = revno + 1
                continue
            if len(matches) > 1:
                raise RuntimeError("revision %s (revno %d) duplicated"
                                   % (revision, revno))
            if matches[0] == "yes":
                self._high_revno = revno
                break
            elif matches[0] == "no":
                self._low_revno = revno
            revno = revno + 1

        if not self._high_revno or not self._low_revno:
            return

        spread = self._high_revno - self._low_revno
        if spread < 0:
            raise RuntimeError("negative spread")
        if spread < 3:
            self._middle_revno = self._low_revno + 1
        else:
            self._middle_revno = self._low_revno + (spread / 2)

    def _switch_wc_to_revno(self, revno):
        self._current.switch(revno)
        self._current.show_rev_log()

    def _set_status(self, revid, status):
        self._items.append((revid, status))

    def change_file_name(self, filename):
        self._filename = filename

    def load(self):
        self._items = []
        if os.path.exists(self._filename):
            f = self._open_for_read()
            for line in f:
                (revid, status) = line.split()
                self._items.append((revid, status))

    def save(self):
        f = self._open_for_write()
        for (revid, status) in self._items:
            f.write("%s %s\n" % (revid, status))

    def set_status_from_revspec(self, revspec, status):
        self._load_bzr_tree()
        revid = revspec[0].in_history(self._bzrbranch).rev_id
        self._set_status(revid, status)

    def set_current(self, status):
        self._set_status(self._current.get_current_revid(), status)

    def bisect(self):
        self._find_current_range()
        if self._middle_revno:
            self._switch_wc_to_revno(self._middle_revno)

class cmd_bisect(Command):
    """Find an interesting commit using a binary search.

    Bisecting, in a nutshell, is a way to find the commit at which
    some testable change was made, such as the introduction of a bug
    or feature.  By identifying a version which did not have the
    interesting change and a later version which did, a developer
    can test for the presence of the change at various points in
    the history, eventually ending up at the precise commit when
    the change was first introduced.

    This command uses subcommands to implement the search, each
    of which changes the state of the bisection.  The
    subcommands are:

    bzr bisect start
        Start a bisect, possibly clearing out a previous bisect.

    bzr bisect yes [-r rev]
        The specified revision (or the current revision, if not given)
        has the characteristic we're looking for,

    bzr bisect no [-r rev]
        The specified revision (or the current revision, if not given)
        does not have the charactistic we're looking for,

    bzr bisect move -r rev
        Switch to a different revision manually.  Use if the bisect
        algorithm chooses a revision that is not suitable.  Try to
        move as little as possible.

    bzr bisect reset
        Clear out a bisection in progress.

    bzr bisect log [-o file]
        Output a log of the current bisection to standard output, or
        to the specified file.

    bzr bisect replay <logfile>
        Replay a previously-saved bisect log, forgetting any bisection
        that might be in progress.
    """

    takes_args = ['subcommand', 'args*']
    takes_options = [Option('output', short_name='o',
                            help='Write log to this file.', type=unicode),
                     'revision']

    def _check(self):
        # Conditions that must be true for most operations to
        # work.

        if not os.path.exists(bisect_info_path):
            raise BzrCommandError("No bisect info found")

    def _set_state(self, revspec, state):
        bl = BisectLog()
        if revspec:
            bl.set_status_from_revspec(revspec, state)
        else:
            bl.set_current(state)
        bl.bisect()
        bl.save()

    def run(self, subcommand, args_list, revision=None, output=None):
        # Handle subcommand parameters.

        log_fn = None
        if subcommand in ('yes', 'no', 'move') and revision:
            pass
        elif subcommand in ('replay',) and args_list and len(args_list) == 1:
            log_fn = args_list[0]
        elif subcommand in ('move',) and not revision:
            raise BzrCommandError("The 'bisect move' command requires a revision.")
        elif args_list or revision:
            raise BzrCommandError("Improper arguments to bisect " + subcommand)

        # Dispatch.

        if subcommand == "start":
            self.start()
        elif subcommand == "yes":
            self.yes(revision)
        elif subcommand == "no":
            self.no(revision)
        elif subcommand == "move":
            self.move(revision)
        elif subcommand == "reset":
            self.reset()
        elif subcommand == "log":
            self.log(output)
        elif subcommand == "replay":
            self.replay(log_fn)

    def reset(self):
        "Reset the bisect state to no state."

        BisectCurrent().reset()
        if os.path.exists(bisect_info_path):
            os.unlink(bisect_info_path)

    def start(self):
        "Reset the bisect state, then prepare for a new bisection."

        self.reset()
        bl = BisectLog()
        bl.set_current("start")
        bl.save()

    def yes(self, revspec):
        "Mark that a given revision has the state we're looking for."

        self._set_state(revspec, "yes")

    def no(self, revspec):
        "Mark that a given revision does not have the state we're looking for."

        self._set_state(revspec, "no")

    def move(self, revspec):
        "Move to a different revision manually."

        bc = BisectCurrent()
        bc.switch(revspec)
        bc.show_rev_log()

    def log(self, filename):
        "Write the current bisect log to a file."

        self._check()

        bl = BisectLog()
        bl.change_file_name(filename)
        bl.save()

    def replay(self, filename):
        """Apply the given log file to a clean state, so the state is
        exactly as it was when the log was saved."""

        self.reset()

        bl = BisectLog(filename)
        bl.change_file_name(bisect_info_path)
        bl.save()

        bl.bisect()

register_command(cmd_bisect)

# Tests.

class BisectTestCase(bzrlib.tests.TestCaseWithTransport):
    def assertRevno(self, rev):
        "Make sure we're at the right revision."

        rev_contents = { 1: "one", 2: "two", 3: "three",
                         4: "four", 5: "five" }

        f = open("test_file")
        if f.read() != rev_contents[rev]:
            raise AssertionError("not at revision %d" % rev)

    def setUp(self):
        bzrlib.tests.TestCaseWithTransport.setUp(self)

        # These tests assume a branch with five revisions.

        self.tree = self.make_branch_and_tree(".")

        f = open("test_file", "w")
        f.write("one")
        f.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), 'test_file')))
        self.tree.commit(message = "add test file")

        file_contents = ["two", "three", "four", "five"]
        for content in file_contents:
            f = open("test_file", "w")
            f.write(content)
            f.close()
            self.tree.commit(message = "make test change")

class BisectCurrentUnitTests(BisectTestCase):
    def testShowLog(self):
        # Not a very good test; just makes sure the code doesn't fail,
        # not that the output makes any sense.
        BisectCurrent().show_rev_log()

    def testSwitchVersions(self):
        bc = BisectCurrent()
        self.assertRevno(5)
        bc.switch(4)
        self.assertRevno(4)

    def testReset(self):
        bc = BisectCurrent()
        bc.switch(4)
        bc.reset()
        self.assertRevno(5)
        assert not os.path.exists(bisect_rev_path)

class BisectLogUnitTests(BisectTestCase):
    def testCreateBlank(self):
        bl = BisectLog()
        bl.save()
        assert os.path.exists(bisect_info_path)

    def testLoad(self):
        open(bisect_info_path, "w").write("rev1 yes\nrev2 no\nrev3 yes\n")

        bl = BisectLog()
        assert len(bl._items) == 3
        assert bl._items[0] == ("rev1", "yes")
        assert bl._items[1] == ("rev2", "no")
        assert bl._items[2] == ("rev3", "yes")

    def testSave(self):
        bl = BisectLog()
        bl._items = [("rev1", "yes"), ("rev2", "no"), ("rev3", "yes")]
        bl.save()

        f = open(bisect_info_path)
        assert f.read() == "rev1 yes\nrev2 no\nrev3 yes\n"

class BisectFuncTests(BisectTestCase):
    def testWorkflow(self):
        # Start up the bisection.  When the two ends are set, we should
        # end up in the middle.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.assertRevno(3)

        # Mark feature as present in the middle.  Should move us
        # halfway back between the current middle and the start.

        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(2)

        # Mark feature as not present.  Since this is only one
        # rev back from the lowest marked revision with the feature,
        # the process should end, with the current rev set to the
        # rev following.

        self.run_bzr(['bisect', 'no'])
        self.assertRevno(3)

    def testMove(self):
        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])

        # Move.

        self.run_bzr(['bisect', 'move', '-r', '2'])
        self.assertRevno(2)

    def testReset(self):
        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Now reset.

        self.run_bzr(['bisect', 'reset'])
        self.assertRevno(5)

    def testLog(self):
        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Now save the log.

        self.run_bzr(['bisect', 'log', '-o', 'bisect_log'])

        # Reset.

        self.run_bzr(['bisect', 'reset'])

        # Read it back in.

        self.run_bzr(['bisect', 'replay', 'bisect_log'])
        self.assertRevno(2)

        # Mark another state, and see if the bisect moves in the
        # right way.

        self.run_bzr(['bisect', 'no'])
        self.assertRevno(3)

def test_suite():
    from bzrlib.tests.TestUtil import TestLoader, TestSuite
    suite = TestSuite()
    suite.addTest(TestLoader().loadTestsFromTestCase(BisectFuncTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(BisectCurrentUnitTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(BisectLogUnitTests))
    return suite
