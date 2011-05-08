#    test_dep3.py -- Testsuite for builddeb dep3.py
#    Copyright (C) 2011 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from cStringIO import StringIO

import rfc822

from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )

from bzrlib.plugins.builddeb.dep3 import (
    describe_origin,
    determine_applied_upstream,
    gather_bugs_and_authors,
    write_dep3_bug_line,
    write_dep3_patch_header,
    )


class Dep3HeaderTests(TestCase):

    def dep3_header(self, description=None, origin=None, forwarded=None,
            bugs=None, authors=None, revision_id=None, last_update=None,
            applied_upstream=None):
        f = StringIO()
        write_dep3_patch_header(f, description=description, origin=origin,
            forwarded=forwarded, bugs=bugs, authors=authors,
            revision_id=revision_id, last_update=last_update,
            applied_upstream=applied_upstream)
        f.seek(0)
        return rfc822.Message(f)

    def test_description(self):
        ret = self.dep3_header(description="This patch fixes the foobar")
        self.assertEquals("This patch fixes the foobar", ret["Description"])

    def test_last_updated(self):
        ret = self.dep3_header(last_update=1304840034)
        self.assertEquals("2011-05-08", ret["Last-Update"])

    def test_revision_id(self):
        ret = self.dep3_header(revision_id="myrevid")
        self.assertEquals("myrevid", ret["X-Bzr-Revision-Id"])

    def test_authors(self):
        authors = [
            "Jelmer Vernooij <jelmer@canonical.com>",
            "James Westby <james.westby@canonical.com>"]
        ret = self.dep3_header(authors=authors)
        self.assertEquals([
            ("Jelmer Vernooij", "jelmer@canonical.com"),
            ("James Westby", "james.westby@canonical.com")],
            ret.getaddrlist("Author"))

    def test_origin(self):
        ret = self.dep3_header(origin="Cherrypick from upstream")
        self.assertEquals("Cherrypick from upstream",
            ret["Origin"])

    def test_forwarded(self):
        ret = self.dep3_header(forwarded="not needed")
        self.assertEquals("not needed",
            ret["Forwarded"])

    def test_applied_upstream(self):
        ret = self.dep3_header(applied_upstream="commit 45")
        self.assertEquals("commit 45", ret["Applied-Upstream"])

    def test_bugs(self):
        bugs = [
            ("http://bugs.debian.org/424242", "fixed"),
            ("https://bugs.launchpad.net/bugs/20110508", "fixed"),
            ("http://bugzilla.samba.org/bug.cgi?id=52", "fixed")]
        ret = self.dep3_header(bugs=bugs)
        self.assertEquals([
            "https://bugs.launchpad.net/bugs/20110508",
            "http://bugzilla.samba.org/bug.cgi?id=52"],
            ret.getheaders("Bug"))
        self.assertEquals(["http://bugs.debian.org/424242"],
            ret.getheaders("Bug-Debian"))

    def test_write_bug_fix_only(self):
        # non-fixed bug lines are ignored
        f = StringIO()
        write_dep3_bug_line(f, "http://bar/", "pending")
        self.assertEquals("", f.getvalue())

    def test_write_normal_bug(self):
        f = StringIO()
        write_dep3_bug_line(f, "http://bugzilla.samba.org/bug.cgi?id=42",
            "fixed")
        self.assertEquals("Bug: http://bugzilla.samba.org/bug.cgi?id=42\n",
            f.getvalue())

    def test_write_debian_bug(self):
        f = StringIO()
        write_dep3_bug_line(f, "http://bugs.debian.org/234354", "fixed")
        self.assertEquals("Bug-Debian: http://bugs.debian.org/234354\n",
            f.getvalue())


class GatherBugsAndAuthors(TestCaseWithTransport):

    def test_none(self):
        branch = self.make_branch(".")
        self.assertEquals((set(), set(), None),
            gather_bugs_and_authors(branch.repository, []))

    def test_multiple_authors(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(authors=["Jelmer Vernooij <jelmer@canonical.com>"],
                timestamp=1304844311, message="msg")
        revid2 = tree.commit(authors=["Max Bowsher <maxb@f2s.com>"],
                timestamp=1304844278, message="msg")
        self.assertEquals((set(), set([
            "Jelmer Vernooij <jelmer@canonical.com>",
            "Max Bowsher <maxb@f2s.com>"]), 1304844311),
            gather_bugs_and_authors(tree.branch.repository, [revid1, revid2]))

    def test_bugs(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(authors=["Jelmer Vernooij <jelmer@canonical.com>"],
                timestamp=1304844311, message="msg", revprops={"bugs":
                    "http://bugs.samba.org/bug.cgi?id=2011 fixed\n"})
        self.assertEquals((
            set([("http://bugs.samba.org/bug.cgi?id=2011", "fixed")]),
            set(["Jelmer Vernooij <jelmer@canonical.com>"]), 1304844311),
            gather_bugs_and_authors(tree.branch.repository, [revid1]))


class DetermineAppliedUpstreamTests(TestCaseWithTransport):

    def test_not_applied(self):
        upstream = self.make_branch_and_tree("upstream")
        feature = self.make_branch_and_tree("feature")
        feature.commit(message="every bloody emperor")
        self.addCleanup(feature.lock_read().unlock)
        self.assertEquals("no",
            determine_applied_upstream(upstream.branch, feature.branch))

    def test_merged(self):
        upstream = self.make_branch_and_tree("upstream")
        upstream.commit(message="initial upstream commit")
        feature = upstream.bzrdir.sprout("feature").open_workingtree()
        feature.commit(message="nutter alert")
        upstream.merge_from_branch(feature.branch)
        upstream.commit(message="merge feature")
        self.addCleanup(upstream.lock_read().unlock)
        self.addCleanup(feature.lock_read().unlock)
        self.assertEquals("merged in revision 2",
            determine_applied_upstream(upstream.branch, feature.branch))


class DescribeOriginTests(TestCaseWithTransport):

    def test_no_public_branch(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(message="msg1")
        self.assertEquals("commit, revision id: %s" % revid1,
            describe_origin(tree.branch, revid1))

    def test_public_branch(self):
        tree = self.make_branch_and_tree(".")
        tree.branch.set_public_branch("http://example.com/public")
        revid1 = tree.commit(message="msg1")
        self.assertEquals("commit, http://example.com/public, revision: 1",
            describe_origin(tree.branch, revid1))
