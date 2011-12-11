# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
# -*- coding: utf-8 -*-
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

"""Tests for pushing revisions from Bazaar into Git."""

from bzrlib.bzrdir import (
    format_registry,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )

from bzrlib.plugins.git.push import (
    InterToGitRepository,
    )


class InterToGitRepositoryTests(TestCaseWithTransport):

    def setUp(self):
        super(InterToGitRepositoryTests, self).setUp()
        self.git_repo = self.make_repository("git",
                format=format_registry.make_bzrdir("git"))
        self.bzr_repo = self.make_repository("bzr", shared=True)

    def _get_interrepo(self):
        self.bzr_repo.lock_read()
        self.addCleanup(self.bzr_repo.unlock)
        return InterRepository.get(self.bzr_repo, self.git_repo)

    def test_instance(self):
        self.assertIsInstance(self._get_interrepo(), InterToGitRepository)

    def test_pointless_fetch_refs(self):
        revidmap, old_refs, new_refs = self._get_interrepo().fetch_refs(lambda x: {}, lossy=False)
        self.assertEquals(old_refs, {'HEAD': ('ref: refs/heads/master', None)})
        self.assertEquals(new_refs, {})

    def test_pointless_lossy_fetch_refs(self):
        revidmap, old_refs, new_refs = self._get_interrepo().fetch_refs(lambda x: {}, lossy=True)
        self.assertEquals(old_refs, {'HEAD': ('ref: refs/heads/master', None)})
        self.assertEquals(new_refs, {})
        self.assertEquals(revidmap, {})

    def test_pointless_missing_revisions(self):
        interrepo = self._get_interrepo()
        interrepo.source_store.lock_read()
        self.addCleanup(interrepo.source_store.unlock)
        self.assertEquals([], list(interrepo.missing_revisions([])))

    def test_missing_revisions_unknown_stop_rev(self):
        interrepo = self._get_interrepo()
        interrepo.source_store.lock_read()
        self.addCleanup(interrepo.source_store.unlock)
        self.assertEquals([],
                list(interrepo.missing_revisions([(None, "unknown")])))

    def test_odd_rename(self):
        # Add initial revision to bzr branch.
        branch = self.bzr_repo.bzrdir.create_branch()
        tree = branch.bzrdir.create_workingtree()
        self.build_tree(["bzr/bar/", "bzr/bar/foobar"])
        tree.add(["bar", "bar/foobar"])
        tree.commit("initial")

        # Add new directory and perform move in bzr branch.
        self.build_tree(["bzr/baz/"])
        tree.add(["baz"])
        tree.rename_one("bar", "baz/IrcDotNet")
        last_revid = tree.commit("rename")

        # Push bzr branch to git branch.
        def decide(x):
            return { "refs/heads/master": (None, last_revid) }
        interrepo = self._get_interrepo()
        revidmap, old_refs, new_refs = interrepo.fetch_refs(decide, lossy=True)
        gitid = revidmap[last_revid][0]
        store = self.git_repo._git.object_store
        commit = store[gitid]
        tree = store[commit.tree]
        tree.check()
        self.expectFailure("fails with KeyError (bug 818318)",
            self.assertTrue, tree["baz"][1] in store)
        baz = store[tree["baz"][1]]
        baz.check()
        ircdotnet = store[baz["IrcDotNet"][1]]
        ircdotnet.check()
        foobar = store[ircdotnet["foobar"][1]]
        foobar.check()
