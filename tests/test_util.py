#    test_util.py -- Testsuite for builddeb util.py
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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

try:
    import hashlib as md5
except ImportError:
    import md5
import os
import shutil

from debian_bundle.changelog import Changelog, Version

from bzrlib.plugins.builddeb.errors import (MissingChangelogError,
                AddChangelogError,
                )
from bzrlib.plugins.builddeb.tests import SourcePackageBuilder
from bzrlib.plugins.builddeb.util import (
                  dget,
                  dget_changes,
                  find_bugs_fixed,
                  find_changelog,
                  find_extra_authors,
                  find_last_distribution,
                  find_thanks,
                  get_commit_info_from_changelog,
                  get_snapshot_revision,
                  lookup_distribution,
                  move_file_if_different,
                  get_parent_dir,
                  recursive_copy,
                  safe_decode,
                  strip_changelog_message,
                  suite_to_distribution,
                  tarball_name,
                  write_if_different,
                  )

from bzrlib import errors as bzr_errors
from bzrlib.tests import (TestCaseWithTransport,
                          TestCaseInTempDir,
                          TestCase,
                          )


class RecursiveCopyTests(TestCaseInTempDir):

    def test_recursive_copy(self):
        os.mkdir('a')
        os.mkdir('b')
        os.mkdir('c')
        os.mkdir('a/d')
        os.mkdir('a/d/e')
        f = open('a/f', 'wb')
        try:
            f.write('f')
        finally:
            f.close()
        os.mkdir('b/g')
        recursive_copy('a', 'b')
        self.failUnlessExists('a')
        self.failUnlessExists('b')
        self.failUnlessExists('c')
        self.failUnlessExists('b/d')
        self.failUnlessExists('b/d/e')
        self.failUnlessExists('b/f')
        self.failUnlessExists('a/d')
        self.failUnlessExists('a/d/e')
        self.failUnlessExists('a/f')


class SafeDecodeTests(TestCase):

    def assertSafeDecode(self, expected, val):
        self.assertEqual(expected, safe_decode(val))

    def test_utf8(self):
        self.assertSafeDecode(u'ascii', 'ascii')
        self.assertSafeDecode(u'\xe7', '\xc3\xa7')

    def test_iso_8859_1(self):
        self.assertSafeDecode(u'\xe7', '\xe7')


cl_block1 = """\
bzr-builddeb (0.17) unstable; urgency=low

  [ James Westby ]
  * Pass max_blocks=1 when constructing changelogs as that is all that is
    needed currently.

 -- James Westby <jw+debian@jameswestby.net>  Sun, 17 Jun 2007 18:48:28 +0100

"""


class FindChangelogTests(TestCaseWithTransport):

    def write_changelog(self, filename):
        f = open(filename, 'wb')
        try:
            f.write(cl_block1)
            f.write("""\
bzr-builddeb (0.16.2) unstable; urgency=low

  * loosen the dependency on bzr. bzr-builddeb seems to be not be broken
    by bzr version 0.17, so remove the upper bound of the dependency.

 -- Reinhard Tartler <siretart@tauware.de>  Tue, 12 Jun 2007 19:45:38 +0100
""")
        finally:
            f.close()

    def test_find_changelog_std(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, False)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_nomerge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        self.assertRaises(MissingChangelogError, find_changelog, tree, False)

    def test_find_changelog_nochangelog(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        self.assertRaises(MissingChangelogError, find_changelog, tree, False)

    def test_find_changelog_nochangelog_merge(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(MissingChangelogError, find_changelog, tree, True)

    def test_find_changelog_symlink(self):
        """When there was a symlink debian -> . then the code used to break"""
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        os.symlink('.', 'debian')
        tree.add(['debian'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_symlink_naughty(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        f = open('changelog', 'wb')
        try:
            f.write('Naughty, naughty')
        finally:
            f.close()
        tree.add(['changelog', 'debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_changelog_not_added(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        self.assertRaises(AddChangelogError, find_changelog, tree, False)


class StripChangelogMessageTests(TestCase):

    def test_None(self):
        self.assertEqual(strip_changelog_message(None), None)

    def test_no_changes(self):
        self.assertEqual(strip_changelog_message([]), [])

    def test_empty_changes(self):
        self.assertEqual(strip_changelog_message(['']), [])

    def test_removes_leading_whitespace(self):
        self.assertEqual(strip_changelog_message(
                    ['foo', '  bar', '\tbaz', '   bang']),
                    ['foo', 'bar', 'baz', ' bang'])

    def test_removes_star_if_one(self):
        self.assertEqual(strip_changelog_message(['  * foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['\t* foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  + foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  - foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  *  foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  *  foo', '     bar']),
                ['foo', 'bar'])

    def test_leaves_start_if_multiple(self):
        self.assertEqual(strip_changelog_message(['  * foo', '  * bar']),
                    ['* foo', '* bar'])
        self.assertEqual(strip_changelog_message(['  * foo', '  + bar']),
                    ['* foo', '+ bar'])
        self.assertEqual(strip_changelog_message(
                    ['  * foo', '  bar', '  * baz']),
                    ['* foo', 'bar', '* baz'])


class TarballNameTests(TestCase):

    def test_tarball_name(self):
        self.assertEqual(tarball_name("package", "0.1"),
                "package_0.1.orig.tar.gz")
        self.assertEqual(tarball_name("package", Version("0.1")),
                "package_0.1.orig.tar.gz")
        self.assertEqual(tarball_name("package", Version("0.1"),
                    format='bz2'), "package_0.1.orig.tar.bz2")
        self.assertEqual(tarball_name("package", Version("0.1"),
                    format='lzma'), "package_0.1.orig.tar.lzma")


class GetRevisionSnapshotTests(TestCase):

    def test_with_snapshot(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4~bzr30"))

    def test_with_snapshot_plus(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4+bzr30"))

    def test_without_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4"))

    def test_non_numeric_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4~bzra"))

    def test_with_svn_snapshot(self):
        self.assertEquals("svn:4242", get_snapshot_revision("0.4.4~svn4242"))

    def test_with_svn_snapshot_plus(self):
        self.assertEquals("svn:2424", get_snapshot_revision("0.4.4+svn2424"))


class SuiteToDistributionTests(TestCase):

    def _do_lookup(self, target):
        return suite_to_distribution(target)

    def lookup_ubuntu(self, target):
        self.assertEqual(self._do_lookup(target), 'ubuntu')

    def lookup_debian(self, target):
        self.assertEqual(self._do_lookup(target), 'debian')

    def lookup_other(self, target):
        self.assertEqual(self._do_lookup(target), None)

    def test_lookup_ubuntu(self):
        self.lookup_ubuntu('intrepid')
        self.lookup_ubuntu('hardy-proposed')
        self.lookup_ubuntu('gutsy-updates')
        self.lookup_ubuntu('feisty-security')
        self.lookup_ubuntu('dapper-backports')

    def test_lookup_debian(self):
        self.lookup_debian('unstable')
        self.lookup_debian('stable-security')
        self.lookup_debian('testing-proposed-updates')
        self.lookup_debian('etch-backports')

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_other("debian")
        self.lookup_other("ubuntu")


class LookupDistributionTests(SuiteToDistributionTests):

    def _do_lookup(self, target):
        return lookup_distribution(target)

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_debian("debian")
        self.lookup_ubuntu("ubuntu")
        self.lookup_ubuntu("Ubuntu")


class MoveFileTests(TestCaseInTempDir):

    def test_move_file_non_extant(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'b', None)
        self.failIfExists('a')
        self.failUnlessExists('b')

    def test_move_file_samefile(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'a', None)
        self.failUnlessExists('a')

    def test_move_file_same_md5(self):
        self.build_tree(['a'])
        md5sum = md5.md5()
        f = open('a', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        shutil.copy('a', 'b')
        move_file_if_different('a', 'b', md5sum.hexdigest())
        self.failUnlessExists('a')
        self.failUnlessExists('b')

    def test_move_file_diff_md5(self):
        self.build_tree(['a', 'b'])
        md5sum = md5.md5()
        f = open('a', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        a_hexdigest = md5sum.hexdigest()
        md5sum = md5.md5()
        f = open('b', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        b_hexdigest = md5sum.hexdigest()
        self.assertNotEqual(a_hexdigest, b_hexdigest)
        move_file_if_different('a', 'b', a_hexdigest)
        self.failIfExists('a')
        self.failUnlessExists('b')
        md5sum = md5.md5()
        f = open('b', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        self.assertEqual(md5sum.hexdigest(), a_hexdigest)


class WriteFileTests(TestCaseInTempDir):

    def test_write_non_extant(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")

    def test_write_file_same(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")

    def test_write_file_different(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")
        write_if_different("bar", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "bar")


class DgetTests(TestCaseWithTransport):

    def test_dget_local(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(builder.dsc_name(), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))

    def test_dget_transport(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(self.get_url(builder.dsc_name()), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))

    def test_dget_missing_dsc(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        # No builder.build()
        self.build_tree(["target/"])
        self.assertRaises(bzr_errors.NoSuchFile, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_file(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        os.unlink(builder.tar_name())
        self.build_tree(["target/"])
        self.assertRaises(bzr_errors.NoSuchFile, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_target(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.assertRaises(bzr_errors.NotADirectory, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_changes(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget_changes(builder.changes_name(), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))
        self.failUnlessExists(os.path.join("target", builder.changes_name()))


class ParentDirTests(TestCase):

    def test_get_parent_dir(self):
        self.assertEqual(get_parent_dir("a"), '')
        self.assertEqual(get_parent_dir("a/"), '')
        self.assertEqual(get_parent_dir("a/b"), 'a')
        self.assertEqual(get_parent_dir("a/b/"), 'a')
        self.assertEqual(get_parent_dir("a/b/c"), 'a/b')


class ChangelogInfoTests(TestCaseWithTransport):

    def test_find_extra_authors_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        authors = find_extra_authors(changes)
        self.assertEqual([], authors)

    def test_find_extra_authors(self):
        changes = ["  * Do foo", "", "  [ A. Hacker ]", "  * Do bar", "",
                   "  [ B. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"A. Hacker", u"B. Hacker"], authors)
        self.assertEqual([unicode]*len(authors), map(type, authors))

    def test_find_extra_authors_utf8(self):
        changes = ["  * Do foo", "", "  [ \xc3\xa1. Hacker ]", "  * Do bar", "",
                   "  [ \xc3\xa7. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"\xe1. Hacker", u"\xe7. Hacker"], authors)
        self.assertEqual([unicode]*len(authors), map(type, authors))

    def test_find_extra_authors_iso_8859_1(self):
        # We try to treat lines as utf-8, but if that fails to decode, we fall
        # back to iso-8859-1
        changes = ["  * Do foo", "", "  [ \xe1. Hacker ]", "  * Do bar", "",
                   "  [ \xe7. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"\xe1. Hacker", u"\xe7. Hacker"], authors)
        self.assertEqual([unicode]*len(authors), map(type, authors))

    def test_find_extra_authors_no_changes(self):
        authors = find_extra_authors([])
        self.assertEqual([], authors)

    def assert_thanks_is(self, changes, expected_thanks):
        thanks = find_thanks(changes)
        self.assertEqual(expected_thanks, thanks)
        self.assertEqual([unicode]*len(thanks), map(type, thanks))

    def test_find_thanks_no_changes(self):
        self.assert_thanks_is([], [])

    def test_find_thanks_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        self.assert_thanks_is(changes, [])

    def test_find_thanks(self):
        changes = ["  * Thanks to A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * Thanks to James A. Hacker"]
        self.assert_thanks_is(changes, [u"James A. Hacker"])
        changes = ["  * Thankyou to B. Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * thanks to A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * thankyou to B. Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * Thanks A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * Thankyou B.  Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * Thanks to Mark A. Super-Hacker"]
        self.assert_thanks_is(changes, [u"Mark A. Super-Hacker"])
        changes = ["  * Thanks to A. Hacker <ahacker@example.com>"]
        self.assert_thanks_is(changes, [u"A. Hacker <ahacker@example.com>"])
        changes = ["  * Thanks to Adeodato Sim\xc3\x83\xc2\xb3"]
        self.assert_thanks_is(changes, [u"Adeodato Sim\xc3\xb3"])
        changes = ["  * Thanks to \xc3\x81deodato Sim\xc3\x83\xc2\xb3"]
        self.assert_thanks_is(changes, [u"\xc1deodato Sim\xc3\xb3"])

    def test_find_bugs_fixed_no_changes(self):
        self.assertEqual([], find_bugs_fixed([], None, _lplib=MockLaunchpad()))

    def test_find_bugs_fixed_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        bugs = find_bugs_fixed(changes, None, _lplib=MockLaunchpad())
        self.assertEqual([], bugs)

    def test_find_bugs_fixed_debian(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * Closes: #12345, 56789", "  * closes:bug45678"]
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(["http://bugs.debian.org/12345 fixed",
                "http://bugs.debian.org/56789 fixed",
                "http://bugs.debian.org/45678 fixed"], bugs)

    def test_find_bugs_fixed_debian_with_ubuntu_links(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * Closes: #12345", "  * closes:bug45678"]
        lplib = MockLaunchpad(debian_bug_to_ubuntu_bugs=
                {"12345": ("998877", "987654"),
                "45678": ("87654",)})
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=lplib)
        self.assertEqual([], lplib.ubuntu_bug_lookups)
        self.assertEqual(["12345", "45678"], lplib.debian_bug_lookups)
        self.assertEqual(["http://bugs.debian.org/12345 fixed",
                "http://bugs.debian.org/45678 fixed",
                "https://launchpad.net/bugs/87654 fixed"], bugs)

    def test_find_bugs_fixed_lp(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * LP: #12345,#56789", "  * lp:  #45678"]
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(["https://launchpad.net/bugs/12345 fixed",
                "https://launchpad.net/bugs/56789 fixed",
                "https://launchpad.net/bugs/45678 fixed"], bugs)

    def test_find_bugs_fixed_lp_with_debian_links(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * LP: #12345", "  * lp:  #45678"]
        lplib = MockLaunchpad(ubuntu_bug_to_debian_bugs=
                {"12345": ("998877", "987654"), "45678": ("87654",)})
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=lplib)
        self.assertEqual([], lplib.debian_bug_lookups)
        self.assertEqual(["12345", "45678"], lplib.ubuntu_bug_lookups)
        self.assertEqual(["https://launchpad.net/bugs/12345 fixed",
                "https://launchpad.net/bugs/45678 fixed",
                "http://bugs.debian.org/87654 fixed"], bugs)

    def test_get_commit_info_none(self):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        message, authors, thanks, bugs = \
                get_commit_info_from_changelog(changelog, wt.branch,
                        _lplib=MockLaunchpad())
        self.assertEqual(None, message)
        self.assertEqual([], authors)
        self.assertEqual([], thanks)
        self.assertEqual([], bugs)

    def test_get_commit_message_info(self):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        changes = ["  [ A. Hacker ]", "  * First change, LP: #12345",
                   "  * Second change, thanks to B. Hacker"]
        author = "J. Maintainer <maint@example.com"
        changelog.new_block(changes=changes, author=author)
        message, authors, thanks, bugs = \
                get_commit_info_from_changelog(changelog, wt.branch,
                        _lplib=MockLaunchpad())
        self.assertEqual("\n".join(strip_changelog_message(changes)), message)
        self.assertEqual([author]+find_extra_authors(changes), authors)
        self.assertEqual(unicode, type(authors[0]))
        self.assertEqual(find_thanks(changes), thanks)
        self.assertEqual(find_bugs_fixed(changes, wt.branch,
                    _lplib=MockLaunchpad()), bugs)

    def assertUnicodeCommitInfo(self, changes):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        author = "J. Maintainer <maint@example.com>"
        changelog.new_block(changes=changes, author=author)
        message, authors, thanks, bugs = \
                get_commit_info_from_changelog(changelog, wt.branch,
                        _lplib=MockLaunchpad())
        self.assertEqual(u'[ \xc1. Hacker ]\n'
                         u'* First ch\xe1nge, LP: #12345\n'
                         u'* Second change, thanks to \xde. Hacker',
                         message)
        self.assertEqual([author, u'\xc1. Hacker'], authors)
        self.assertEqual(unicode, type(authors[0]))
        self.assertEqual([u'\xde. Hacker'], thanks)
        self.assertEqual(['https://launchpad.net/bugs/12345 fixed'], bugs)

    def test_get_commit_info_utf8(self):
        changes = ["  [ \xc3\x81. Hacker ]",
                   "  * First ch\xc3\xa1nge, LP: #12345",
                   "  * Second change, thanks to \xc3\x9e. Hacker"]
        self.assertUnicodeCommitInfo(changes)

    def test_get_commit_info_iso_8859_1(self):
        # Changelogs aren't always well-formed UTF-8, so we fall back to
        # iso-8859-1 if we fail to decode utf-8.
        changes = ["  [ \xc1. Hacker ]",
                   "  * First ch\xe1nge, LP: #12345",
                   "  * Second change, thanks to \xde. Hacker"]
        self.assertUnicodeCommitInfo(changes)


class MockLaunchpad(object):

    def __init__(self, debian_bug_to_ubuntu_bugs={},
            ubuntu_bug_to_debian_bugs={}):
        self.debian_bug_to_ubuntu_bugs = debian_bug_to_ubuntu_bugs
        self.ubuntu_bug_to_debian_bugs = ubuntu_bug_to_debian_bugs
        self.debian_bug_lookups = []
        self.ubuntu_bug_lookups = []

    def ubuntu_bugs_for_debian_bug(self, debian_bug):
        self.debian_bug_lookups.append(debian_bug)
        try:
            return self.debian_bug_to_ubuntu_bugs[debian_bug]
        except KeyError:
            return []

    def debian_bugs_for_ubuntu_bug(self, ubuntu_bug):
        self.ubuntu_bug_lookups.append(ubuntu_bug)
        try:
            return self.ubuntu_bug_to_debian_bugs[ubuntu_bug]
        except KeyError:
            return []


class FindLastDistributionTests(TestCase):

    def create_changelog(self, *distributions):
        changelog = Changelog()
        changes = ["  [ A. Hacker ]", "  * Something"]
        author = "J. Maintainer <maint@example.com"
        for distro in distributions:
            changelog.new_block(changes=changes, author=author,
                                distributions=distro)
        return changelog

    def test_first(self):
        changelog = self.create_changelog("unstable")
        self.assertEquals("unstable", find_last_distribution(changelog))

    def test_second(self):
        changelog = self.create_changelog("unstable", "UNRELEASED")
        self.assertEquals("UNRELEASED", changelog.distributions)
        self.assertEquals("unstable", find_last_distribution(changelog))

    def test_empty(self):
        changelog = self.create_changelog()
        self.assertEquals(None, find_last_distribution(changelog))

    def test_only_unreleased(self):
        changelog = self.create_changelog("UNRELEASED")
        self.assertEquals(None, find_last_distribution(changelog))

