#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
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

import commands
import os
import shutil
import subprocess
import tempfile
import urlparse

from debian_bundle.changelog import Version

from bzrlib import (
    urlutils,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.commands import Command
from bzrlib.errors import (BzrCommandError,
                           NoWorkingTree,
                           NotBranchError,
                           FileExists,
                           )
from bzrlib.export import export
from bzrlib.option import Option
from bzrlib.revisionspec import RevisionSpec
from bzrlib.trace import info, warning
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.builddeb import (
    default_build_dir,
    default_orig_dir,
    default_result_dir,
    default_conf,
    local_conf,
    global_conf,
    test_suite,
    )
from bzrlib.plugins.builddeb.builder import (
                     DebBuild,
                     )
from bzrlib.plugins.builddeb.config import DebBuildConfig
from bzrlib.plugins.builddeb.errors import BuildFailedError
from bzrlib.plugins.builddeb.hooks import run_hook
from bzrlib.plugins.builddeb.import_dsc import (
        DistributionBranch,
        DistributionBranchSet,
        DscCache,
        DscComp,
        )
from bzrlib.plugins.builddeb.merge_package import fix_ancestry_as_needed
from bzrlib.plugins.builddeb.source_distiller import (
        FullSourceDistiller,
        MergeModeDistiller,
        NativeSourceDistiller,
        )
from bzrlib.plugins.builddeb.upstream import (
        UpstreamProvider,
        UpstreamBranchSource,
        get_upstream_sources,
        )
from bzrlib.plugins.builddeb.util import (find_changelog,
        get_export_upstream_revision,
        find_last_distribution,
        lookup_distribution,
        suite_to_distribution,
        tarball_name,
        dget_changes,
        )

dont_purge_opt = Option('dont-purge',
    help="Don't purge the build directory after building.")
result_opt = Option('result-dir',
    help="Directory in which to place the resulting package files.", type=str)
builder_opt = Option('builder',
    help="Command to build the package.", type=str)
merge_opt = Option('merge',
    help='Merge the debian part of the source in to the upstream tarball.')
split_opt = Option('split',
    help="Automatically create an .orig.tar.gz from a full source branch.")
build_dir_opt = Option('build-dir',
    help="The dir to use for building.", type=str)
orig_dir_opt = Option('orig-dir',
    help="Directory containing the .orig.tar.gz files. For use when only"
       +"debian/ is versioned.", type=str)
native_opt = Option('native',
    help="Build a native package.")
export_upstream_opt = Option('export-upstream',
    help="Create the .orig.tar.gz from a bzr branch before building.",
    type=unicode)
export_upstream_revision_opt = Option('export-upstream-revision',
    help="Select the upstream revision that will be exported.",
    type=str)
no_user_conf_opt = Option('no-user-config',
    help="Stop builddeb from reading the user's config file. Used mainly "
    "for tests.")


def debuild_config(tree, working_tree, no_user_config):
    """Obtain the Debuild configuration object.

    :param tree: A Tree object, can be a WorkingTree or RevisionTree.
    :param working_tree: Whether the tree is a working tree.
    :param no_user_config: Whether to skip the user configuration
    """
    config_files = []
    user_config = None
    if (working_tree and tree.has_filename(local_conf)):
        if tree.path2id(local_conf) is None:
            config_files.append((tree.get_file_byname(local_conf), True,
                        "local.conf"))
        else:
            warning('Not using configuration from %s as it is versioned.')
    if not no_user_config:
        config_files.append((global_conf, True))
        user_config = global_conf
    if tree.path2id(default_conf):
        config_files.append((tree.get_file(tree.path2id(default_conf)), False,
                    "default.conf"))
    config = DebBuildConfig(config_files, tree=tree)
    config.set_user_config(user_config)
    return config


class cmd_builddeb(Command):
    """Builds a Debian package from a branch.

    If BRANCH is specified it is assumed that the branch you wish to build is
    located there. If it is not specified then the current directory is used.

    By default, if a working tree is found, it is used to build. Otherwise the
    last committed revision found in the branch is used. To force building the
    last committed revision use --revision -1. You can also specify any other
    revision with the --revision option.

    If you only wish to export the package, and not build it (especially useful
    for merge mode), use --export-only.

    To leave the build directory when the build is completed use --dont-purge.

    Specify the command to use when building using the --builder option, by
    default "debuild" is used. It can be overriden by setting the "builder"
    variable in you configuration. You can specify extra options to build with
    by adding them to the end of the command, after using "--" to indicate the
    end of the options to builddeb itself. The builder that you specify must
    accept the options you provide at the end of its command line.

    You can also specify directories to use for different things. --build-dir
    is the directory to build the packages beneath, which defaults to
    '../build-area'. '--orig-dir' specifies the directory that contains the
    .orig.tar.gz files , which defaults to '..'. '--result-dir' specifies where
    the resulting package files should be placed, which defaults to '..'.
    --result-dir will have problems if you use a build command that places
    the results in a different directory.

    The --reuse option will be useful if you are in merge mode, and the upstream
    tarball is very large. It attempts to reuse a build directory from an earlier
    build. It will fail if one doesn't exist, but you can create one by using 
    --export-only. 

    --quick allows you to define a quick-builder in your configuration files, 
    which will be used when this option is passed. It defaults to 'fakeroot 
    debian/rules binary'. It is overriden if --builder is passed. Using this
    and --reuse allows for fast rebuilds.
    """
    working_tree_opt = Option('working-tree', help="This option has no effect.",
                              short_name='w')
    export_only_opt = Option('export-only', help="Export only, don't build.",
                             short_name='e')
    use_existing_opt = Option('use-existing',
                              help="Use an existing build directory.")
    quick_opt = Option('quick', help="Quickly build the package, uses "
                       +"quick-builder, which defaults to \"fakeroot "
                       +"debian/rules binary\".")
    reuse_opt = Option('reuse', help="Try to avoid exporting too much on each "
                       +"build. Only works in merge mode; it saves unpacking "
                       +"the upstream tarball each time. Implies --dont-purge "
                       +"and --use-existing.")
    source_opt = Option('source', help="Build a source package.",
                        short_name='S')
    result_compat_opt = Option('result', help="Present only for compatibility "
            "with bzr-builddeb <= 2.0. Use --result-dir instead.")
    takes_args = ['branch_or_build_options*']
    aliases = ['bd']
    takes_options = [working_tree_opt, export_only_opt,
        dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt,
        build_dir_opt, orig_dir_opt, split_opt,
        export_upstream_opt, export_upstream_revision_opt,
        quick_opt, reuse_opt, native_opt,
        source_opt, 'revision',
        no_user_conf_opt, result_compat_opt]

    def _get_tree_and_branch(self, location):
        if location is None:
            location = "."
        is_local = urlparse.urlsplit(location)[0] in ('', 'file')
        if is_local:
            os.chdir(location)
        tree, branch, relpath = BzrDir.open_containing_tree_or_branch(location)
        return tree, branch, is_local

    def _get_build_tree(self, revision, tree, branch):
        if revision is None and tree is not None:
            info("Building using working tree")
            working_tree = True
        else:
            if revision is None:
                revid = branch.last_revision()
            elif len(revision) == 1:
                revid = revision[0].in_history(branch).rev_id
            else:
                raise BzrCommandError('bzr builddeb --revision takes exactly one '
                                      'revision specifier.')
            info("Building branch from revision %s", revid)
            tree = branch.repository.revision_tree(revid)
            working_tree = False
        return tree, working_tree

    def _build_type(self, config, merge, native, split):
        if not merge:
            merge = config.merge
        if merge:
            info("Running in merge mode")
            native = False
            split = False
        else:
            if not native:
                native = config.native
            if native:
                info("Running in native mode")
                split = False
            else:
                if not split:
                    split = config.split
                if split:
                    info("Running in split mode")
        return merge, native, split

    def _get_build_command(self, config, builder, quick, build_options):
        if builder is None:
            if quick:
                builder = config.quick_builder
                if builder is None:
                    builder = "fakeroot debian/rules binary"
            else:
                builder = config.builder
                if builder is None:
                    builder = "debuild"
        if build_options:
            builder += " " + " ".join(build_options)
        return builder

    def _get_dirs(self, config, is_local, result_dir, result, build_dir, orig_dir):
        if result_dir is None:
            result_dir = result
        if result_dir is None:
            if is_local:
                result_dir = config.result_dir
            else:
                result_dir = config.user_result_dir
        if result_dir is not None:
            result_dir = os.path.realpath(result_dir)
        if build_dir is None:
            if is_local:
                build_dir = config.build_dir or default_build_dir
            else:
                build_dir = config.user_build_dir or 'build-area'
        if orig_dir is None:
            if is_local:
                orig_dir = config.orig_dir or default_orig_dir
            else:
                orig_dir = config.user_orig_dir or 'build-area'
        return result_dir, build_dir, orig_dir

    def _branch_and_build_options(self, branch_or_build_options_list,
            source=False):
        branch = None
        build_options = []
        source_opt = False
        if branch_or_build_options_list is not None:
            for opt in branch_or_build_options_list:
                if opt.startswith("-") or branch is not None:
                    build_options.append(opt)
                    if opt == "-S" or opt == "--source":
                        source_opt = True
                else:
                    branch = opt
        if source and not source_opt:
            build_options.append("-S")
        if source_opt:
            source = True
        return branch, build_options, source

    def _get_upstream_branch(self, merge, export_upstream,
            export_upstream_revision, config, version):
        upstream_branch = None
        upstream_revision = None
        if merge:
            if export_upstream is None:
                export_upstream = config.export_upstream
            if export_upstream:
                upstream_branch = Branch.open(export_upstream)
                upstream_branch.lock_read()
                try:
                    if export_upstream_revision is None:
                        export_upstream_revision = \
                                    get_export_upstream_revision(config,
                                            version=version)
                    if export_upstream_revision is None:
                        upstream_revision = \
                                upstream_branch.last_revision()
                    else:
                        upstream_revspec = RevisionSpec.from_string(
                                export_upstream_revision)
                        upstream_revision = \
                            upstream_revspec.as_revision_id(upstream_branch)
                finally:
                    upstream_branch.unlock()
        return (upstream_branch, upstream_revision)

    def run(self, branch_or_build_options_list=None, verbose=False,
            working_tree=False,
            export_only=False, dont_purge=False, use_existing=False,
            result_dir=None, builder=None, merge=False, build_dir=None,
            export_upstream=None, export_upstream_revision=None,
            orig_dir=None, split=None,
            quick=False, reuse=False, native=False,
            source=False, revision=None, no_user_config=False, result=None):
        if result is not None:
            warning("--result is deprected, use --result-dir instead")
        branch, build_options, source = self._branch_and_build_options(
                branch_or_build_options_list, source)
        tree, branch, is_local = self._get_tree_and_branch(branch)
        tree, working_tree = self._get_build_tree(revision, tree, branch)
        tree.lock_read()
        try:
            config = debuild_config(tree, working_tree, no_user_config)
            if reuse:
                info("Reusing existing build dir")
                dont_purge = True
                use_existing = True
            merge, native, split = self._build_type(config, merge, native, split)
            if (not merge and not native and not split and
                tree.inventory.root.children.keys() == ["debian"]):
                # Default to merge mode if there's only a debian/ directory
                merge = True
            build_cmd = self._get_build_command(config, builder, quick,
                    build_options)
            (changelog, larstiq) = find_changelog(tree, merge)
            result_dir, build_dir, orig_dir = self._get_dirs(config, is_local,
                    result_dir, result, build_dir, orig_dir)

            upstream_branch, upstream_revision = \
                    self._get_upstream_branch(merge, export_upstream,
                            export_upstream_revision, config,
                            changelog.version)

            upstream_provider = UpstreamProvider(
                    changelog.package, changelog.version,
                    orig_dir, get_upstream_sources(tree, branch,
                    larstiq=larstiq, upstream_branch=upstream_branch,
                    upstream_revision=upstream_revision, allow_split=split))

            if merge:
                distiller_cls = MergeModeDistiller
            elif native:
                distiller_cls = NativeSourceDistiller
            else:
                distiller_cls = FullSourceDistiller

            distiller = distiller_cls(tree, upstream_provider,
                    larstiq=larstiq, use_existing=use_existing,
                    is_working_tree=working_tree)

            build_source_dir = os.path.join(build_dir,
                    "%s-%s" % (changelog.package,
                               changelog.version.upstream_version))

            builder = DebBuild(distiller, build_source_dir, build_cmd,
                    use_existing=use_existing)
            builder.prepare()
            run_hook(tree, 'pre-export', config)
            builder.export()
            if not export_only:
                run_hook(tree, 'pre-build', config, wd=build_source_dir)
                builder.build()
                run_hook(tree, 'post-build', config, wd=build_source_dir)
                if not dont_purge:
                    builder.clean()
                if source:
                    arch = "source"
                else:
                    status, arch = commands.getstatusoutput(
                        'dpkg-architecture -qDEB_BUILD_ARCH')
                    if status > 0:
                        raise BzrCommandError("Could not find the build architecture")
                changes = "%s_%s_%s.changes" % (changelog.package,
                        str(changelog.version), arch)
                changes_path = os.path.join(build_dir, changes)
                if not os.path.exists(changes_path):
                    if result_dir is not None:
                        raise BzrCommandError("Could not find the .changes "
                                "file from the build: %s" % changes_path)
                else:
                    target_dir = result_dir or default_result_dir
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)
                    dget_changes(changes_path, target_dir)
        finally:
            tree.unlock()


class cmd_merge_upstream(Command):
    """Merges a new upstream version into the current branch.

    Takes a new upstream version and merges it in to your branch, so that your
    packaging changes are applied to the new version.

    You must supply the source to import from, and the version number of the
    new release. The source can be a .tar.gz, .tar, .tar.bz2, .tgz or .zip
    archive, or a directory. The source may also be a remote file.

    You must supply the version number of the new upstream release
    using --version.

    The distribution this version is targetted at can be specified with
    --distribution. This will be used to guess the version number, so you
    can always correct it in the changelog.

    If there is no debian changelog in the branch to retrieve the package
    name from then you must pass the --package option. If this version
    will change the name of the source package then you can use this option
    to set the new name.
    """
    takes_args = ['location?', 'upstream_branch?']
    aliases = ['mu']

    package_opt = Option('package', help="The name of the source package.",
                         type=str)
    version_opt = Option('version', help="The version number of this release.",
                         type=str)
    distribution_opt = Option('distribution', help="The distribution that "
            "this release is targetted at.", type=str)
    directory_opt = Option('directory',
                           help='Working tree into which to merge.',
                           short_name='d', type=unicode)

    takes_options = [package_opt, no_user_conf_opt, version_opt,
            distribution_opt, directory_opt, 'revision', 'merge-type']

    def _update_changelog(self, tree, version, distribution_name, changelog,
            package):
        from bzrlib.plugins.builddeb.merge_upstream import package_version
        if "~bzr" in str(version) or "+bzr" in str(version):
            entry_description = "New upstream snapshot."
        else:
            entry_description = "New upstream release."
        proc = subprocess.Popen(["/usr/bin/dch", "-v",
                str(package_version(version, distribution_name)),
                "-D", "UNRELEASED", "--release-heuristic", "changelog",
                entry_description], cwd=tree.basedir)
        proc.wait()
        if proc.returncode != 0:
            raise BzrCommandError('Adding a new changelog stanza after the '
                    'merge had completed failed. Add the new changelog entry '
                    'yourself, review the merge, and then commit.')

    def run(self, location=None, upstream_branch=None, version=None, distribution=None,
            package=None, no_user_config=None, directory=".", revision=None,
            merge_type=None):
        from bzrlib.plugins.builddeb.errors import MissingChangelogError
        from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
        from bzrlib.plugins.builddeb.merge_upstream import upstream_branch_version
        tree, _ = WorkingTree.open_containing(directory)
        tree.lock_write()
        try:
            # Check for uncommitted changes.
            if tree.changes_from(tree.basis_tree()).has_changed():
                raise BzrCommandError("There are uncommitted changes in the "
                        "working tree. You must commit before using this "
                        "command.")
            config = debuild_config(tree, tree, no_user_config)
            if config.merge:
                raise BzrCommandError("Merge upstream in merge mode is not "
                        "yet supported.")
            if config.native:
                raise BzrCommandError("Merge upstream in native mode is not "
                        "yet supported.")

            if location is None:
                if config.upstream_branch is not None:
                    location = config.upstream_branch
                else:
                    raise BzrCommandError("No location specified to merge")
            changelog = None
            try:
                changelog = find_changelog(tree, False, max_blocks=2)[0]
                current_version = changelog.version
                if package is None:
                    package = changelog.package
                if distribution is None:
                    distribution = find_last_distribution(changelog)
                    if distribution is not None:
                        info("Using distribution %s" % distribution)
            except MissingChangelogError:
                current_version = None
            if distribution is None:
                info("No distribution specified, and no changelog, "
                        "assuming 'debian'")
                distribution = "debian"

            if package is None:
                raise BzrCommandError("You did not specify --package, and "
                        "there is no changelog from which to determine the "
                        "package name, which is needed to know the name to "
                        "give the .orig.tar.gz. Please specify --package.")

            no_tarball = False
            if upstream_branch is None:
                try:
                    upstream_branch = Branch.open(location)
                    no_tarball = True
                except NotBranchError:
                    upstream_branch = None
            else:
                upstream_branch = Branch.open(upstream_branch)

            distribution = distribution.lower()
            distribution_name = lookup_distribution(distribution)
            if distribution_name is None:
                raise BzrCommandError("Unknown target distribution: %s" \
                            % distribution)

            upstream_revision = None
            if upstream_branch:
                if revision is not None:
                    if len(revision) > 1:
                        raise BzrCommandError("merge-upstream takes only a single --revision")
                    upstream_revspec = revision[0]
                    upstream_revision = upstream_revspec.as_revision_id(upstream_branch)
                else:
                    upstream_revision = upstream_branch.last_revision()

            if no_tarball and revision is not None:
                raise BzrCommandError("--revision is not allowed when merging a tarball")

            if version is None:
                if upstream_branch and no_tarball:
                    version = upstream_branch_version(upstream_branch,
                            upstream_revision, package,
                            current_version.upstream_version)
                    info("Using version string %s for upstream branch." % (version))
                else:
                    raise BzrCommandError("You must specify the "
                            "version number using --version.")

            version = Version(version)
            orig_dir = config.orig_dir or default_orig_dir
            orig_dir = os.path.join(tree.basedir, orig_dir)
            if not os.path.exists(orig_dir):
                os.makedirs(orig_dir)
            dest_name = tarball_name(package, version.upstream_version)
            tarball_filename = os.path.join(orig_dir, dest_name)

            if upstream_branch and no_tarball:
                upstream = UpstreamBranchSource(upstream_branch, 
                        upstream_revision)
                upstream.get_specific_version(package, version.upstream_version,
                        orig_dir)
            else:
                try:
                    repack_tarball(location, dest_name, target_dir=orig_dir)
                except FileExists:
                    raise BzrCommandError("The target file %s already exists, and is either "
                                          "different to the new upstream tarball, or they "
                                          "are of different formats. Either delete the target "
                                          "file, or use it as the argument to import."
                                          % dest_name)
            db = DistributionBranch(tree.branch, None, tree=tree)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            conflicts = db.merge_upstream(tarball_filename, version,
                    current_version, upstream_branch=upstream_branch,
                    upstream_revision=upstream_revision,
                    merge_type=merge_type)

            self._update_changelog(tree, version, distribution_name, changelog,
                    package)
        finally:
            tree.unlock()
        info("The new upstream version has been imported.")
        if conflicts:
            info("You should now resolve the conflicts, review the changes, and then commit.")
        else:
            info("You should now review the changes and then commit.")


class cmd_import_dsc(Command):
    """Import a series of source packages.

    Provide a number of source packages (.dsc files), and they will
    be imported to create a branch with history that reflects those
    packages.

    The first argument is the distribution that these source packages
    were uploaded to, one of "debian" or "ubuntu". It can also
    be the target distribution from the changelog, e.g. "unstable",
    which will be resolved to the correct distribution.

    You can also specify a file (possibly remote) that contains a
    list of source packages (.dsc files) to import using the --file
    option. Each line is taken to be a URI or path to import. The
    sources specified in the file are used in addition to those
    specified on the command line.

    If you have an existing branch containing packaging and you want to
    import a .dsc from an upload done from outside the version control
    system you can use this command.
    """

    takes_args = ['files*']

    filename_opt = Option('file', help="File containing URIs of source "
                          "packages to import.", type=str, argname="filename",
                          short_name='F')

    takes_options = [filename_opt]

    def import_many(self, db, files_list, orig_target):
        cache = DscCache()
        files_list.sort(cmp=DscComp(cache).cmp)
        if not os.path.exists(orig_target):
            os.makedirs(orig_target)
        for dscname in files_list:
            dsc = cache.get_dsc(dscname)
            def get_dsc_part(from_transport, filename):
                from_f = from_transport.get(filename)
                contents = from_f.read()
                to_f = open(os.path.join(orig_target, filename), 'wb')
                try:
                    to_f.write(contents)
                finally:
                    to_f.close()
            base, filename = urlutils.split(dscname)
            from_transport = cache.get_transport(dscname)
            get_dsc_part(from_transport, filename)
            for file_details in dsc['files']:
                name = file_details['name']
                get_dsc_part(from_transport, name)
            db.import_package(os.path.join(orig_target, filename))

    def run(self, files_list, filename=None):
        from bzrlib.plugins.builddeb.errors import MissingChangelogError
        try:
            tree = WorkingTree.open_containing('.')[0]
        except NotBranchError:
            raise BzrCommandError("There is no tree to import the packages in to")
        tree.lock_write()
        try:
            if tree.changes_from(tree.basis_tree()).has_changed():
                raise BzrCommandError("There are uncommitted changes in the "
                        "working tree. You must commit before using this "
                        "command")
            if files_list is None:
                files_list = []
            if filename is not None:
                if isinstance(filename, unicode):
                    filename = filename.encode('utf-8')
                base_dir, path = urlutils.split(filename)
                sources_file = get_transport(base_dir).get(path)
                for line in sources_file:
                    line.strip()
                    files_list.append(line)
            if len(files_list) < 1:
                raise BzrCommandError("You must give the location of at least one "
                                      "source package to install, or use the "
                                      "--file option.")
            config = debuild_config(tree, tree, False)
            if config.merge:
                raise BzrCommandError("import-dsc in merge mode is not "
                        "yet supported.")
            orig_dir = config.orig_dir or default_orig_dir
            orig_target = os.path.join(tree.basedir, default_orig_dir)
            db = DistributionBranch(tree.branch, None, tree=tree)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            try:
                (changelog, larstiq) = find_changelog(tree, False)
                last_version = changelog.version
            except MissingChangelogError:
                last_version = None
            tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir,
                        '..'))
            try:
                if last_version is not None:
                    if not db.has_upstream_version_in_packaging_branch(
                            last_version.upstream_version):
                        raise BzrCommandError("Unable to find the tag for "
                                "the previous upstream version, %s, in the "
                                "branch: %s" % (last_version,
                                    db.upstream_tag_name(last_version)))
                    upstream_tip = db.revid_of_upstream_version_from_branch(
                            last_version)
                    db.extract_upstream_tree(upstream_tip, tempdir)
                else:
                    db._create_empty_upstream_tree(tempdir)
                self.import_many(db, files_list, orig_target)
            finally:
                shutil.rmtree(tempdir)
        finally:
            tree.unlock()


class cmd_bd_do(Command):
    """Run a command in an exported package, copying the result back.

    For a merge mode package the full source is not available, making some
    operations difficult. This command allows you to run any command in an
    exported source directory, copying the resulting debian/ directory back
    to your branch if the command is successful.

    For instance:

      bzr bd-do

    will run a shell in the unpacked source. Any changes you make in the
    ``debian/`` directory (and only those made in that directory) will be copied
    back to the branch. If you exit with a non-zero exit code (e.g. "exit 1"),
    then the changes will not be copied back.

    You can also specify single commands to be run, e.g.

      bzr bd-do "dpatch-edit-patch 01-fix-build"

    Note that only the first argument is used as the command, and so the above
    example had to be quoted.
    """

    takes_args = ['command*']

    def run(self, command_list=None):
        t = WorkingTree.open_containing('.')[0]
        config = debuild_config(t, t, False)

        if not config.merge:
            raise BzrCommandError("This command only works for merge mode "
                                  "packages. See /usr/share/doc/bzr-builddeb"
                                  "/user_manual/merge.html for more information.")

        give_instruction = False
        if command_list is None:
            try:
                command_list = [os.environ['SHELL']]
            except KeyError:
                command_list = ["/bin/sh"]
            give_instruction = True
        (changelog, larstiq) = find_changelog(t, True)
        build_dir = config.build_dir
        if build_dir is None:
            build_dir = default_build_dir
        orig_dir = config.orig_dir
        if orig_dir is None:
            orig_dir = default_orig_dir
        upstream_provider = UpstreamProvider(changelog.package, 
                changelog.version.upstream_version, orig_dir, 
                get_upstream_sources(t, t.branch, larstiq=larstiq))

        distiller = MergeModeDistiller(t, upstream_provider,
                larstiq=larstiq)

        build_source_dir = os.path.join(build_dir,
                changelog.package + "-" + changelog.version.upstream_version)

        command = " ".join(command_list)

        builder = DebBuild(distiller, build_source_dir, command)
        builder.prepare()
        run_hook(t, 'pre-export', config)
        builder.export()
        info('Running "%s" in the exported directory.' % (command))
        if give_instruction:
            info('If you want to cancel your changes then exit with a non-zero '
                 'exit code, e.g. run "exit 1".')
        try:
            builder.build()
        except BuildFailedError:
            raise BzrCommandError('Not updating the working tree as the '
                    'command failed.')
        info("Copying debian/ back")
        if larstiq:
            destination = ''
        else:
            destination = 'debian/'
        destination = os.path.join(t.basedir, destination)
        source_debian = os.path.join(build_source_dir, 'debian')
        for filename in os.listdir(source_debian):
            proc = subprocess.Popen('cp -apf "%s" "%s"' % (
                 os.path.join(source_debian, filename), destination),
                 shell=True)
            proc.wait()
            if proc.returncode != 0:
                raise BzrCommandError('Copying back debian/ failed')
        builder.clean()
        info('If any files were added or removed you should run "bzr add" or '
             '"bzr rm" as appropriate.')


class cmd_mark_uploaded(Command):
    """Mark that this branch has been uploaded, prior to pushing it.
    
    When a package has been uploaded we want to mark the revision
    that it was uploaded in. This command automates doing that
    by marking the current tip revision with the version indicated
    in debian/changelog.
    """
    force = Option('force', help="Mark the upload even if it is already "
            "marked.")

    takes_options = [merge_opt, no_user_conf_opt, force]

    def run(self, merge=False, no_user_config=False, force=None):
        t = WorkingTree.open_containing('.')[0]
        t.lock_write()
        try:
            if t.changes_from(t.basis_tree()).has_changed():
              raise BzrCommandError("There are uncommitted changes in the "
                      "working tree. You must commit before using this "
                      "command")
            config = debuild_config(t, t, no_user_config)
            if not merge:
                merge = config.merge
            (changelog, larstiq) = find_changelog(t, merge)
            distributions = changelog.distributions.strip()
            target_dist = distributions.split()[0]
            distribution_name = suite_to_distribution(target_dist)
            if distribution_name is None:
                raise BzrCommandError("Unknown target distribution: %s" \
                        % target_dist)
            db = DistributionBranch(t.branch, None)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            if db.has_version(changelog.version):
                if not force:
                    raise BzrCommandError("This version has already been "
                            "marked uploaded. Use --force to force marking "
                            "this new version.")
            tag_name = db.tag_version(changelog.version)
            self.outf.write("Tag '%s' created.\n" % tag_name)
        finally:
            t.unlock()


class cmd_merge_package(Command):
    """Merges source packaging branch into target packaging branch.

    This will first check whether the upstream branches have diverged.
    In that case an attempt will be made to fix upstream ancestry so that
    the user only needs dealing wth packaging branch merge issues.
    In the opposite case a normal merge will be performed.
    """
    takes_args = ['source']

    def run(self, source):
        source_branch = target_branch = None
        # Get the target branch.
        try:
            tree = WorkingTree.open_containing('.')[0]
            target_branch = tree.branch
        except NotBranchError:
            raise BzrCommandError(
                "There is no tree to merge the source branch in to")
        # Get the source branch.
        try:
            source_branch = Branch.open(source)
        except NotBranchError:
            raise BzrCommandError("Invalid source branch URL?")

        fix_ancestry_as_needed(tree, source_branch)

        # Merge source packaging branch in to the target packaging branch.
        tree.merge_from_branch(source_branch)


class cmd_test_builddeb(Command):
    """Run the builddeb test suite"""

    hidden = True

    def run(self):
        from bzrlib.tests import selftest
        passed = selftest(test_suite_factory=test_suite)
        # invert for shell exit code rules
        return not passed
