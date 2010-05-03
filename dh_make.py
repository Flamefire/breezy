try:
    import hashlib as md5
except ImportError:
    import md5
import os
import shutil
import sys
import subprocess

from bzrlib import (
    bzrdir,
    revision as mod_revision,
    trace,
    transport,
    workingtree,
    )
from bzrlib import errors as bzr_errors

from bzrlib.plugins.builddeb import (
    default_orig_dir,
    import_dsc,
    upstream,
    util,
    )


def _get_tree(package_name):
    try:
        tree = workingtree.WorkingTree.open(".")
    except bzr_errors.NotBranchError:
        if os.path.exists(package_name):
            raise bzr_errors.BzrCommandError("Either run the command from an "
                    "existing branch of upstream, or move %s aside "
                    "and a new branch will be created there."
                    % package_name)
        to_transport = transport.get_transport(package_name)
        tree = to_transport.ensure_base()
        try:
            a_bzrdir = bzrdir.BzrDir.open_from_transport(to_transport)
        except bzr_errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base,
                                   possible_transports=[to_transport])
            a_bzrdir = branch.bzrdir
        else:
            if a_bzrdir.has_branch():
                raise bzr_errors.AlreadyBranchError(package_name)
            branch = a_bzrdir.create_branch()
            a_bzrdir.create_workingtree()
        try:
            tree = a_bzrdir.open_workingtree()
        except bzr_errors.NoWorkingTree:
            tree = a_bzrdir.create_workingtree()
    return tree


def _get_tarball(tree, tarball, package_name, version, use_v3=False):
    from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
    config = util.debuild_config(tree, tree, False)
    orig_dir = config.orig_dir or default_orig_dir
    orig_dir = os.path.join(tree.basedir, orig_dir)
    if not os.path.exists(orig_dir):
        os.makedirs(orig_dir)
    format = None
    if use_v3:
        if tarball.endswith(".tar.bz2") or tarball.endswith(".tbz2"):
            format = "bz2"
    dest_name = util.tarball_name(package_name, version, format=format)
    tarball_filename = os.path.join(orig_dir, dest_name)
    trace.note("Fetching tarball")
    repack_tarball(tarball, dest_name, target_dir=orig_dir,
            force_gz=not use_v3)
    provider = upstream.UpstreamProvider(package_name, "%s-1" % version,
            orig_dir, [])
    provider.provide(os.path.join(tree.basedir, ".."))
    return tarball_filename, util.md5sum_filename(tarball_filename)


def import_upstream(tarball, package_name, version, use_v3=False):
    tree = _get_tree(package_name)
    if tree.branch.last_revision() != mod_revision.NULL_REVISION:
        parents = [tree.branch.last_revision()]
    else:
        parents = []
    tarball_filename, md5sum = _get_tarball(tree, tarball,
            package_name, version, use_v3=use_v3)
    db = import_dsc.DistributionBranch(tree.branch, tree.branch, tree=tree,
            upstream_tree=tree)
    dbs = import_dsc.DistributionBranchSet()
    dbs.add_branch(db)
    db.import_upstream_tarball(tarball_filename, version, parents, md5sum=md5sum)
    return tree


def run_dh_make(tree, package_name, version, use_v3=False):
    if not tree.has_filename("debian"):
        tree.mkdir("debian")
    # FIXME: give a nice error on 'debian is not a directory'
    if tree.path2id("debian") is None:
        tree.add("debian")
    if use_v3:
        if not tree.has_filename("debian/source"):
            tree.mkdir("debian/source")
        if tree.path2id("debian/source") is None:
            tree.add("debian/source")
        f = open("debian/source/format")
        try:
            f.write("3.0 (quilt)\n")
        finally:
            f.close()
        if tree.path2id("debian/source/format") is None:
            tree.add("debian/source/format")
    command = ["dh_make", "--addmissing", "--packagename",
                "%s_%s" % (package_name, version)]
    proc = subprocess.Popen(command, cwd=tree.basedir,
            preexec_fn=util.subprocess_setup, stdin=sys.stdin)
    retcode = proc.wait()
    if retcode != 0:
        raise bzr_errors.BzrCommandError("dh_make failed.")
    for fn in os.listdir(tree.abspath("debian")):
        if not fn.endswith(".ex") and not fn.endswith(".EX"):
            tree.add(os.path.join("debian", fn))
