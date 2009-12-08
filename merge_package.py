#    merge_package.py -- The plugin for bzr
#    Copyright (C) 2009 Canonical Ltd.
#
#    :Author: Muharem Hrnjadovic <muharem@ubuntu.com>
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

import os
import shutil
import tempfile

from debian_bundle.changelog import Version

from bzrlib.plugins.builddeb.errors import (
    SharedUpstreamConflictsWithTargetPackaging)
from bzrlib.plugins.builddeb.import_dsc import DistributionBranch
from bzrlib.plugins.builddeb.util import find_changelog


def _latest_version(branch):
    """Version of the most recent source package upload in the given `branch`.
    
    :param branch: A Branch object containing the source upload of interest.
    """
    changelog, _ignore = find_changelog(branch.basis_tree(), False)

    return changelog.version


def _upstream_version_data(source, target):
    """Most recent upstream versions/revision IDs of the merge source/target.

    Please note: both packaging branches must have been read-locked
    beforehand.

    :param source: The merge source branch.
    :param target: The merge target branch.
    """
    results = list()
    for branch in (source, target):
        db = DistributionBranch(branch, branch)
        uver = _latest_version(branch).upstream_version
        results.append((Version(uver),
                    db.revid_of_upstream_version_from_branch(uver)))

    return results


def fix_ancestry_as_needed(tree, source):
    """Manipulate the merge target's ancestry to avoid upstream conflicts.

    Merging J->I given the following ancestry tree is likely to result in
    upstream merge conflicts:

    debian-upstream                 ,------------------H
                       A-----------B                    \
    ubuntu-upstream     \           \`-------G           \
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    Here there was a new upstream release (G) that Ubuntu packaged (I), and
    then another one that Debian packaged, skipping G, at H and J.

    Now, the way to solve this is to introduce the missing link.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    at K, which isn't a real merge, as we just use the tree from H, but add
    G as a parent and then we merge that in to Ubuntu.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \      \
    debian-packaging      \ ,---------D--------\-----------J      \
                           C           \        \                  \
    ubuntu-packaging        `----E------F--------I------------------L

    At this point we can merge J->L to merge the Debian and Ubuntu changes.

    :param tree: The `WorkingTree` of the merge target branch.
    :param source: The merge source (packaging) branch.
    """
    upstreams_diverged = False
    t_upstream_reverted = False
    target = tree.branch

    source.lock_read()
    try:
        tree.lock_write()
        try:
            # "Unpack" the upstream versions and revision ids for the merge
            # source and target branch respectively.
            [(us_ver, us_revid), (ut_ver, ut_revid)] = _upstream_version_data(source, target)

            # Did the upstream branches of the merge source/target diverge?
            graph = source.repository.get_graph(target.repository)
            upstreams_diverged = (len(graph.heads([us_revid, ut_revid])) > 1)

            # No, we're done!
            if not upstreams_diverged:
                return (upstreams_diverged, t_upstream_reverted)

            # Instantiate a `DistributionBranch` object for the merge target
            # (packaging) branch.
            db = DistributionBranch(tree.branch, tree.branch)
            tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir, '..'))

            try:
                # Extract the merge target's upstream tree into a temporary
                # directory.
                db.extract_upstream_tree(ut_revid, tempdir)
                tmp_target_utree = db.upstream_tree

                # Merge upstream branch tips to obtain a shared upstream parent.
                # This will add revision K (see graph above) to a temporary merge
                # target upstream tree.
                tmp_target_utree.lock_write()
                try:
                    if us_ver > ut_ver:
                        # The source upstream tree is more recent and the
                        # temporary target tree needs to be reshaped to match it.
                        tmp_target_utree.revert(
                            None, source.repository.revision_tree(us_revid))
                        t_upstream_reverted = True

                    tmp_target_utree.set_parent_ids((ut_revid, us_revid))
                    tmp_target_utree.commit(
                        'Prepared upstream tree for merging into target branch.')
                    # Repository updates during a held lock are not visible,
                    # hence the call to refresh the data in the /target/ repo.
                    tree.branch.repository.refresh_data()

                    # Merge shared upstream parent into the target merge branch. This
                    # creates revison L in the digram above.
                    conflicts = tree.merge_from_branch(tmp_target_utree.branch)
                    if conflicts > 0:
                        raise SharedUpstreamConflictsWithTargetPackaging()
                    else:
                        tree.commit('Merging shared upstream rev into target branch.')

                finally:
                    tmp_target_utree.unlock()
            finally:
                shutil.rmtree(tempdir)
        finally:
            tree.unlock()
    finally:
        source.unlock()

    return (upstreams_diverged, t_upstream_reverted)
