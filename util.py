#    util.py -- Utility functions
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
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
import shutil
import tempfile
import os
import re

from bzrlib.trace import mutter

from debian_bundle import deb822
from debian_bundle.changelog import Changelog, ChangelogParseError

from bzrlib import (
        bugtracker,
        errors,
        urlutils,
        )
from bzrlib.transport import get_transport
from bzrlib.plugins.builddeb.errors import (
                MissingChangelogError,
                AddChangelogError,
                UnparseableChangelog,
                )


def recursive_copy(fromdir, todir):
    """Copy the contents of fromdir to todir.

    Like shutil.copytree, but the destination directory must already exist
    with this method, rather than not exists for shutil.
    """
    mutter("Copying %s to %s", fromdir, todir)
    for entry in os.listdir(fromdir):
        path = os.path.join(fromdir, entry)
        if os.path.isdir(path):
            tosubdir = os.path.join(todir, entry)
            if not os.path.exists(tosubdir):
                os.mkdir(tosubdir)
            recursive_copy(path, tosubdir)
        else:
            shutil.copy(path, todir)


def find_changelog(t, merge):
    """Find the changelog in the given tree.

    First looks for 'debian/changelog'. If "merge" is true will also
    look for 'changelog'.

    The returned changelog is created with 'max_blocks=1' and
    'allow_empty_author=True'. The first to try and prevent old broken
    changelog entries from causing the command to fail, and the
    second as some people do this but still want to build.

    "larstiq" is a subset of "merge" mode. It indicates that the
    '.bzr' dir is at the same level as 'changelog' etc., rather
    than being at the same level as 'debian/'.

    :param t: the Tree to look in.
    :param merge: whether this is a "merge" package.
    :return: (changelog, larstiq) where changelog is the Changelog,
        and larstiq is a boolean indicating whether the file is at
        'changelog' if merge was given, False otherwise.
    """
    changelog_file = 'debian/changelog'
    larstiq = False
    t.lock_read()
    try:
        if not t.has_filename(changelog_file):
            if merge:
                #Assume LarstiQ's layout (.bzr in debian/)
                changelog_file = 'changelog'
                larstiq = True
                if not t.has_filename(changelog_file):
                    raise MissingChangelogError('"debian/changelog" or '
                            '"changelog"')
            else:
                raise MissingChangelogError('"debian/changelog"')
        elif merge and t.has_filename('changelog'):
            # If it is a "larstiq" pacakge and debian is a symlink to
            # "." then it will have found debian/changelog. Try and detect
            # this.
            if (t.kind(t.path2id('debian')) == 'symlink' and 
                t.get_symlink_target(t.path2id('debian')) == '.'):
                changelog_file = 'changelog'
                larstiq = True
        mutter("Using '%s' to get package information", changelog_file)
        changelog_id = t.path2id(changelog_file)
        if changelog_id is None:
            raise AddChangelogError(changelog_file)
        contents = t.get_file_text(changelog_id)
    finally:
       t.unlock()
    changelog = Changelog()
    try:
        changelog.parse_changelog(contents, max_blocks=1, allow_empty_author=True)
    except ChangelogParseError, e:
        raise UnparseableChangelog(str(e))
    return changelog, larstiq


def strip_changelog_message(changes):
    """Strip a changelog message like debcommit does.

    Takes a list of changes from a changelog entry and applies a transformation
    so the message is well formatted for a commit message.

    :param changes: a list of lines from the changelog entry
    :return: another list of lines with blank lines stripped from the start
        and the spaces the start of the lines split if there is only one logical
        entry.
    """
    if not changes:
        return changes
    while changes and changes[-1] == '':
        changes.pop()
    while changes and changes[0] == '':
        changes.pop(0)

    whitespace_column_re = re.compile(r'  |\t')
    changes = map(lambda line: whitespace_column_re.sub('', line, 1), changes)

    leader_re = re.compile(r'[ \t]*[*+-] ')
    count = len(filter(leader_re.match, changes))
    if count == 1:
        return map(lambda line: leader_re.sub('', line, 1).lstrip(), changes)
    else:
        return changes


def tarball_name(package, version):
    """Return the name of the .orig.tar.gz for the given package and version.

    :param package: the name of the source package.
    :param version: the upstream version of the package.
    :return: a string that is the name of the upstream tarball to use.
    """
    return "%s_%s.orig.tar.gz" % (package, str(version))


def get_snapshot_revision(upstream_version):
    """Return the upstream revision specifier if specified in the upstream version.

    When packaging an upstream snapshot some people use +vcsnn or ~vcsnn to indicate
    what revision number of the upstream VCS was taken for the snapshot. This given
    an upstream version number this function will return an identifier of the
    upstream revision if it appears to be a snapshot. The identifier is a string
    containing a bzr revision spec, so it can be transformed in to a revision.

    :param upstream_version: a string containing the upstream version number.
    :return: a string containing a revision specifier for the revision of the
        upstream branch that the snapshot was taken from, or None if it doesn't
        appear to be a snapshot.
    """
    match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
    if match is not None:
        return match.groups()[0]
    match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
    if match is not None:
        return "svn:%s" % match.groups()[0]
    return None


def suite_to_distribution(suite):
    """Infer the distribution from a suite.

    When passed the name of a suite (anything in the distributions field of
    a changelog) it will infer the distribution from that (i.e. Debian or
    Ubuntu).

    :param suite: the string containing the suite
    :return: "debian", "ubuntu", or None if the distribution couldn't be inferred.
    """
    debian_releases = ('woody', 'sarge', 'etch', 'lenny', 'squeeze', 'stable',
            'testing', 'unstable', 'experimental', 'frozen')
    debian_targets = ('', '-security', '-proposed-updates', '-backports')
    ubuntu_releases = ('warty', 'hoary', 'breezy', 'dapper', 'edgy',
            'feisty', 'gutsy', 'hardy', 'intrepid', 'jaunty')
    ubuntu_targets = ('', '-proposed', '-updates', '-security', '-backports')
    all_debian = [r + t for r in debian_releases for t in debian_targets]
    all_ubuntu = [r + t for r in ubuntu_releases for t in ubuntu_targets]
    if suite in all_debian:
        return "debian"
    if suite in all_ubuntu:
        return "ubuntu"
    return None


def lookup_distribution(distribution_or_suite):
    """Get the distribution name based on a distribtion or suite name.

    :param distribution_or_suite: a string that is either the name of
        a distribution or a suite.
    :return: a string with a distribution name or None.
    """
    if distribution_or_suite.lower() in ("debian", "ubuntu"):
        return distribution_or_suite.lower()
    return suite_to_distribution(distribution_or_suite)


def move_file_if_different(source, target, md5sum):
    if os.path.exists(target):
        if os.path.samefile(source, target):
            return
        t_md5sum = md5.md5()
        target_f = open(target)
        try:
            for line in target_f:
                t_md5sum.update(line)
        finally:
            target_f.close()
        if t_md5sum.hexdigest() == md5sum:
            return
    shutil.move(source, target)


def write_if_different(contents, target):
    md5sum = md5.md5()
    md5sum.update(contents)
    fd, temp_path = tempfile.mkstemp("builddeb-rename-")
    fobj = os.fdopen(fd, "wd")
    try:
        try:
            fobj.write(contents)
        finally:
            fobj.close()
        move_file_if_different(temp_path, target, md5sum.hexdigest())
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _download_part(name, base_transport, target_dir, md5sum):
    part_base_dir, part_path = urlutils.split(name)
    f_t = base_transport
    if part_base_dir != '':
        f_t = base_transport.clone(part_base_dir)
    f_f = f_t.get(part_path)
    try:
        target_path = os.path.join(target_dir, part_path)
        fd, temp_path = tempfile.mkstemp(prefix="builldeb-")
        fobj = os.fdopen(fd, "wb")
        try:
            try:
                shutil.copyfileobj(f_f, fobj)
            finally:
                fobj.close()
            move_file_if_different(temp_path, target_path, md5sum)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    finally:
        f_f.close()


def _dget(cls, dsc_location, target_dir):
    if not os.path.isdir(target_dir):
        raise errors.NotADirectory(target_dir)
    base_dir, path = urlutils.split(dsc_location)
    dsc_t = get_transport(base_dir)
    dsc_contents = dsc_t.get_bytes(path)
    dsc = cls(dsc_contents)
    for file_details in dsc['files']:
        name = file_details['name']
        _download_part(name, dsc_t, target_dir, file_details['md5sum'])
    write_if_different(dsc_contents, os.path.join(target_dir, path))


def dget(dsc_location, target_dir):
    return _dget(deb822.Dsc, dsc_location, target_dir)


def dget_changes(changes_location, target_dir):
    return _dget(deb822.Changes, changes_location, target_dir)


def get_parent_dir(target):
    parent = os.path.dirname(target)
    if os.path.basename(target) == '':
        parent = os.path.dirname(parent)
    return parent


def find_bugs_fixed(changes, branch):
    bugs = []
    for change in changes:
        for match in re.finditer("closes:\s*(?:bug)?\#?\s?\d+"
                "(?:,\s*(?:bug)?\#?\s?\d+)*", change,
                re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\d+", closes_list):
                bug_url = bugtracker.get_bug_url("deb", branch,
                        match.group(0))
                bugs.append(bug_url + " fixed")
        for match in re.finditer("lp:\s+\#\d+(?:,\s*\#\d+)*",
                change, re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\d+", closes_list):
                bug_url = bugtracker.get_bug_url("lp", branch,
                        match.group(0))
                bugs.append(bug_url + " fixed")
    return bugs


def find_extra_authors(changes):
    extra_author_re = re.compile(r"\s*\[([^\]]+)]\s*", re.UNICODE)
    authors = []
    for change in changes:
        # Parse out any extra authors.
        match = extra_author_re.match(change.decode("utf-8"))
        if match is not None:
            new_author = match.group(1).strip()
            already_included = False
            for author in authors:
                if author.startswith(new_author):
                    already_included = True
                    break
            if not already_included:
                authors.append(new_author.encode("utf-8"))
    return authors


def find_thanks(changes):
    thanks_re = re.compile(r"[tT]hank(?:(?:s)|(?:you))(?:\s*to)?"
            "((?:\s+(?:(?:[A-Z]\.)|(?:[A-Z]\w+(?:-[A-Z]\w+)*)))+"
            "(?:\s+<[^@>]+@[^@>]+>)?)",
            re.UNICODE)
    thanks = []
    changes_str = " ".join(changes).decode("utf-8")
    for match in thanks_re.finditer(changes_str):
        if thanks is None:
            thanks = []
        thanks_str = match.group(1).strip()
        thanks_str = re.sub(r"\s+", " ", thanks_str)
        thanks.append(thanks_str.encode("utf-8"))
    return thanks


def get_commit_info_from_changelog(changelog, branch):
    """Retrieves the messages from the last section of debian/changelog.

    Reads the latest stanza of debian/changelog and returns the
    text of the changes in that section. It also returns other
    information about the change, including the authors of the change,
    anyone that is thanked, and the bugs that are declared fixed by it.

    :return: a tuple (message, authors, thanks, bugs). message is the
        commit message that should be used. authors is a list of strings,
        with those that contributed to the change, thanks is a list
        of string, with those who were thanked in the changelog entry.
        bugs is a list of bug URLs like for --fixes.
        If the information is not available then any can be None.
    """
    message = None
    authors = []
    thanks = []
    bugs = []
    if changelog._blocks:
        block = changelog._blocks[0]
        authors = [block.author]
        changes = strip_changelog_message(block.changes())
        authors += find_extra_authors(changes)
        bugs = find_bugs_fixed(changes, branch)
        thanks = find_thanks(changes)
        message = "\n".join(changes)
    return (message, authors, thanks, bugs)
