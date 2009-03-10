#    merge_upstream.py -- Merge new upstream versions of packages.
#    Copyright (C) 2007 Reinhard Tartler <siretart@tauware.de>
#                  2007 James Westby <jw+debian@jameswestby.net>
#                  2008 Jelmer Vernooij <jelmer@samba.org>
#
#    Code is also taken from bzrtools, which is
#             (C) 2005, 2006, 2007 Aaron Bentley <aaron.bentley@utoronto.ca>
#             (C) 2005, 2006 Canonical Limited.
#             (C) 2006 Michael Ellerman.
#    and distributed under the GPL, version 2 or later.
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

import itertools

from debian_bundle.changelog import Version

from bzrlib.revisionspec import RevisionSpec

from bzrlib.plugins.builddeb.util import get_snapshot_revision


TAG_PREFIX = "upstream-"


def upstream_version_add_revision(upstream_branch, version_string, revid):
    """Update the revision in a upstream version string.

    :param branch: Branch in which the revision can be found
    :param version_string: Original version string
    :param revid: Revision id of the revision
    """
    revno = upstream_branch.revision_id_to_revno(revid)
  
    if "+bzr" in version_string:
        return "%s+bzr%d" % (version_string[:version_string.rfind("+bzr")], revno)

    if "~bzr" in version_string:
        return "%s~bzr%d" % (version_string[:version_string.rfind("~bzr")], revno)

    rev = upstream_branch.repository.get_revision(revid)
    svn_revmeta = getattr(rev, "svn_meta", None)
    if svn_revmeta is not None:
        svn_revno = svn_revmeta.revnum

        if "+svn" in version_string:
            return "%s+svn%d" % (version_string[:version_string.rfind("+svn")], svn_revno)
        if "~svn" in version_string:
            return "%s~svn%d" % (version_string[:version_string.rfind("~svn")], svn_revno)
        return "%s+svn%d" % (version_string, svn_revno)

    return "%s+bzr%d" % (version_string, revno)


def _upstream_branch_version(revhistory, reverse_tag_dict, package, 
                            previous_version, add_rev):
    """Determine the version string of an upstream branch.

    The upstream version is determined from the most recent tag
    in the upstream branch. If that tag does not point at the last revision, 
    the revision number is added to it (<version>+bzr<revno>).

    If there are no tags set on the upstream branch, the previous Debian 
    version is used and combined with the bzr revision number 
    (usually <version>+bzr<revno>).

    :param revhistory: Branch revision history.
    :param reverse_tag_dict: Reverse tag dictionary (revid -> list of tags)
    :param package: Name of package.
    :param previous_version: Previous upstream version in debian changelog.
    :param add_rev: Function that can add a revision suffix to a version string.
    :return: Name of the upstream revision.
    """
    if revhistory == []:
        # No new version to merge
        return Version(previous_version)
    for r in reversed(revhistory):
        if r in reverse_tag_dict:
            # If there is a newer version tagged in branch, 
            # convert to upstream version 
            # return <upstream_version>+bzr<revno>
            for tag in reverse_tag_dict[r]:
                upstream_version = upstream_tag_to_version(tag,
                                                   package=package)
                if upstream_version is not None:
                    if r != revhistory[-1]:
                        upstream_version.upstream_version = add_rev(
                          upstream_version.upstream_version, revhistory[-1])
                    return upstream_version
    return Version(add_rev(previous_version, revhistory[-1]))


def upstream_branch_version(upstream_branch, upstream_revision, package,
        previous_version):
    dotted_revno = upstream_branch.revision_id_to_dotted_revno(upstream_revision)
    if len(dotted_revno) > 1:
        revno = -2
    else:
        revno = dotted_revno[0]
    revhistory = upstream_branch.revision_history()
    previous_revision = get_snapshot_revision(previous_version)
    if previous_revision is not None:
        previous_revspec = RevisionSpec.from_string(previous_revision)
        previous_revno, _ = previous_revspec.in_history(upstream_branch)
        # Trim revision history - we don't care about any revisions 
        # before the revision of the previous version
    else:
        previous_revno = 0
    revhistory = revhistory[previous_revno:revno+1]
    return _upstream_branch_version(revhistory,
            upstream_branch.tags.get_reverse_tag_dict(), package,
            previous_version,
            lambda version, revision: upstream_version_add_revision(upstream_branch, version, revision))


def upstream_tag_to_version(tag_name, package=None):
    """Take a tag name and return the upstream version, or None."""
    if tag_name.startswith(TAG_PREFIX):
        return Version(tag_name[len(TAG_PREFIX):])
    if (package is not None and (
          tag_name.startswith("%s-" % package) or
          tag_name.startswith("%s_" % package))):
        return Version(tag_name[len(package)+1:])
    if tag_name.startswith("release-"):
        return Version(tag_name[len("release-"):])
    if tag_name[0] == "v" and tag_name[1].isdigit():
        return Version(tag_name[1:])
    if all([c.isdigit() or c in (".", "~") for c in tag_name]):
        return Version(tag_name)
    return None


def package_version(merged_version, distribution_name):
    """Determine the package version from the merged version.

    :param merged_version: Merged version string
    :param distribution_name: Distribution the package is for
    """
    ret = Version(merged_version)
    if merged_version.debian_version is not None:
        prev_packaging_revnum = int("".join(itertools.takewhile(
                        lambda x: x.isdigit(),
                        merged_version.debian_version)))
    else:
        prev_packaging_revnum = 0
    if distribution_name == "ubuntu":
        ret.debian_version = "%dubuntu1" % prev_packaging_revnum
    else:
        ret.debian_version = "%d" % (prev_packaging_revnum+1)
    return ret
