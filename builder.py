#    builder.py -- Classes for building packages
#    Copyright (C) 2006, 2007 James Westby <jw+debian@jameswestby.net>
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

import glob
import shutil
import subprocess
import tarfile
import tempfile
import os

from debian_bundle.changelog import Version

from bzrlib.branch import Branch
from bzrlib.errors import NoWorkingTree
from bzrlib.export import export
from bzrlib.revisionspec import RevisionSpec
from bzrlib.trace import info, mutter
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.builddeb.changes import DebianChanges
from bzrlib.plugins.builddeb.errors import (DebianError,
                    NoSourceDirError,
                    BuildFailedError,
                    StopBuild,
                    MissingChanges,
                    )
from bzrlib.plugins.builddeb.util import recursive_copy, tarball_name

def remove_dir(base, dir):
  """Removes a directory from within a base."""
  
  remove_dir = os.path.join(base, dir)
  if os.path.isdir(remove_dir) and not os.path.islink(remove_dir):
    shutil.rmtree(remove_dir)

def remove_bzrbuilddeb_dir(dir):
  """Removes the .bzr-builddeb dir from the specfied directory."""

  #XXX: Is this what we want??
  remove_dir(dir, ".bzr-builddeb")

def remove_debian_dir(dir):
  """Remove the debian/ dir from the specified directory."""

  remove_dir(dir, "debian")


class UpstreamExporter(object):

  def __init__(self, branch, dest, tarball_base, export_prepull=False,
               export_revision=None, stop_on_no_change=False):
    self.branch = branch
    self.dest = dest
    self.tarball_base = tarball_base
    self.export_prepull = export_prepull
    self.export_revision = export_revision
    self.stop_on_no_change = stop_on_no_change

  def export(self):
    if self.export_prepull:
      try:
        tree_to = WorkingTree.open(self.branch)
        branch_to = tree_to.branch
      except NoWorkingTree:
        tree_to = None
        branch_to = Branch.open(self.branch)
      location = branch_to.get_parent()
      if location is None:
        raise DebianError('No default pull location for '+self.branch+ \
                          ', run "bzr pull location" in that branch to set ' \
                          'one up')
      branch_from = Branch.open(location)
      info('Pulling the upstream branch.')
      if branch_from.last_revision() == branch_to.last_revision():
        if self.stop_on_no_change:
          raise StopBuild('No changes to upstream branch')
        info('Nothing to pull')
      else:
        if tree_to is not None:
          count = tree_to.pull(branch_from)
        else:
          count = branch_to.pull(branch_from)
        info('Pulled %d revision(s).', int(count))
      b = branch_to
    else:
      b = Branch.open(self.branch)

    if self.export_revision is None:
      rev_id = b.last_revision()
    else:
      rev_spec = RevisionSpec.from_string(self.export_revision)
      rev_id = rev_spec.in_history(b).rev_id

    info('Exporting upstream source from %s, revision %s',
         self.branch, rev_id)

    t = b.repository.revision_tree(rev_id)
    info(self.tarball_base)
    export(t, self.dest, 'tgz', self.tarball_base)
    return True


class DebBuild(object):
  """The object that does the building work."""

  def __init__(self, properties, tree, _is_working_tree=False):
    """Create a builder.

    properties:
        an instance of a DebBuildProperties class that the builder should
        query to know where to do it's work.
    tree:
        the tree that the user wants to build.
    """
    self._properties = properties
    self._tree = tree
    self._is_working_tree = _is_working_tree

  def _prepare_working_tree(self):
    if self._is_working_tree:
      for (dp, ie) in self._tree.inventory.iter_entries():
        ie._read_tree_state(dp, self._tree)

  def prepare(self, keep_source_dir=False):
    """Do any preparatory steps that should be run before the build.

    It checks that everything is well, and that some needed dirs are
    created.
    """
    build_dir = self._properties.build_dir()
    info("Preparing the build area: %s", build_dir);
    if not os.path.exists(build_dir):
      os.makedirs(build_dir)
    source_dir = self._properties.source_dir()
    if os.path.exists(source_dir):
      if not keep_source_dir:
        info("Purging the build dir: %s", source_dir)
        shutil.rmtree(source_dir)
      else:
        info("Not purging build dir as requested: %s", build_dir)
    else:
      if keep_source_dir:
        raise NoSourceDirError;

  def _watchfile_name(self):
    watchfile = 'debian/watch'
    if self._properties.larstiq():
      watchfile = 'watch'
    return watchfile

  def _has_watch(self):
    watchfile = self._watchfile_name()
    if not self._tree.has_filename(watchfile):
      info("There is no debian/watch file, so can't use that to"
           " retrieve upstream tarball")
      return False
    if self._tree.path2id(watchfile) is None:
      info("There is a debian/watch file, but it needs to be added to the "
           "branch before I can use it to get the upstream tarball")
      return False
    return True

  def _get_upstream_from_watch(self):
    (tmp, tempfilename) = tempfile.mkstemp()
    tmp = os.fdopen(tmp, 'wb')
    watch_id = self._tree.path2id(self._watchfile_name())
    assert watch_id is not None, "watchfile must be in the tree"
    watch = self._tree.get_file_text(watch_id)
    tmp.write(watch)
    tmp.close()
    info("Using uscan to look for the upstream tarball")
    try:
      r = os.system("uscan --upstream-version %s --force-download --rename "
                    "--package %s --watchfile %s --check-dirname-level 0" % \
                    (self._properties.upstream_version(),
                     self._properties.package(), tempfilename))
      if r != 0:
        raise DebianError("uscan failed to retrieve the upstream tarball")
    finally:
      os.unlink(tempfilename)
    # Tarball is now renamed in the parent dir, either as .tar.gz or .tar.bz2
    from repack_tarball import repack_tarball
    fetched_tarball = os.path.join('..', self._tarball_name())
    desired_tarball = self._tarball_name()
    if not os.path.exists(fetched_tarball):
      fetched_tarball = fetched_tarball[:-2] + 'bz2'
      if not os.path.exists(fetched_tarball):
        raise DebianError("Could not find the upstream tarball after uscan "
                          "downloaded it.")
    repack_tarball(fetched_tarball, desired_tarball,
                   target_dir=self._properties.tarball_dir())
    os.unlink(fetched_tarball)

  def _get_upstream_from_archive(self):
    import apt_pkg
    apt_pkg.init()
    sources = apt_pkg.GetPkgSrcRecords()
    sources.Restart()
    package = self._properties.package()
    version = self._properties.upstream_version()
    found = False
    while sources.Lookup(package):
      if version == Version(sources.Version).upstream_version:
        tarball_dir = self._properties.tarball_dir()
        if not os.path.exists(tarball_dir):
            os.makedirs(tarball_dir)
        command = 'apt-get source -y --tar-only %s=%s' % \
            (package, sources.Version)
        proc = subprocess.Popen(command, shell=True, cwd=tarball_dir)
        proc.wait()
        if proc.returncode != 0:
          return False
        return True
    if not found:
      return False


  def _find_tarball(self):
    """Find the upstream tarball and return it's location.

    This method will check that the upstream tarball is available, and
    will return its location. If it is not an exception will be raised.
    """
    tarballdir = self._properties.tarball_dir()
    tarball = os.path.join(tarballdir,self._tarball_name())
    info("Looking for %s to use as upstream source", tarball)
    if not os.path.exists(tarball):
      tarballdir = os.path.join('..', 'tarballs')
      found = False
      if tarballdir != self._properties.tarball_dir():
        compat_tarball = os.path.join(tarballdir,self._tarball_name())
        info("For compatibility looking for %s to use as upstream source",
                compat_tarball)
        if os.path.exists(compat_tarball):
          found = True
          tarball = compat_tarball
      if not found:
        if self._get_upstream_from_archive():
          return tarball
        if not self._has_watch():
          raise DebianError('Could not find upstream tarball at '+tarball)
        else:
          if not os.path.exists(tarballdir):
            os.mkdir(tarballdir)
          else:
            if not os.path.isdir(tarballdir):
              raise DebianError('%s is not a directory.' % tarballdir)
          self._get_upstream_from_watch()
    return tarball

  def _tarball_name(self):
    """Returns the name that the upstream tarball should have."""
    package = self._properties.package()
    upstream = self._properties.upstream_version()
    return tarball_name(package, upstream)
  
  def _export_upstream_branch(self):
    return False

  def export(self, use_existing=False):
    """Export the package in to a clean dir for building.

    This does all that is needed to set up a clean tree in the build dir
    so that it can be built later.
    """
    # It's not documented the use_existing will use the same 
    # tarball, and it doesn't save much here, but we will
    # do it anyway.
    # TODO: should we still copy the tarball across if the target doesn't
    # exists when use_existing is True. It would save having to remember
    # state, but kind of goes against the name.
    if not use_existing:
      exported = self._export_upstream_branch()
      if not exported:
        # Just copy the tarball across, no need to unpack it.
        tarball = self._find_tarball()
        build_dir = self._properties.build_dir()
        shutil.copyfile(tarball, os.path.join(build_dir, self._tarball_name()))
    source_dir = self._properties.source_dir()
    info("Exporting to %s", source_dir)
    tree = self._tree
    tree.lock_read()
    try:
      self._prepare_working_tree()
      export(tree,source_dir,None,None)
    finally:
      tree.unlock()
    remove_bzrbuilddeb_dir(source_dir)

  def build(self, builder):
    """This builds the package using the supplied command."""
    source_dir = self._properties.source_dir()
    info("Building the package in %s, using %s", source_dir, builder)
    proc = subprocess.Popen(builder, shell=True, cwd=source_dir)
    proc.wait()
    if proc.returncode != 0:
      raise BuildFailedError;

  def clean(self):
    """This removes the build directory."""
    source_dir = self._properties.source_dir()
    info("Cleaning build dir: %s", source_dir)
    shutil.rmtree(source_dir)

  def move_result(self, result, allow_missing=False, arch=None):
    """Moves the files that resulted from the build to the given dir.

    The files are found by reading the changes file.
    """
    package = self._properties.package()
    version = self._properties.full_version_no_epoch()
    try:
        changes = DebianChanges(package, version,
                self._properties.build_dir(), arch=arch)
    except MissingChanges:
        if allow_missing:
            return
        raise
    info("Placing result in %s", result)
    files = changes.files()
    if not os.path.exists(result):
      os.makedirs(result)
    mutter("Moving %s to %s", changes.filename(), result)
    shutil.move(changes.filename(), result)
    mutter("Moving all files given in %s", changes.filename())
    for file in files:
      filename = os.path.join(self._properties.build_dir(), file['name'])
      mutter("Moving %s to %s", filename, result)
      try:
        shutil.move(filename, result)
      except IOError, e:
        if e.errno <> 2:
          raise
        raise DebianError("The file " + filename + " is described in the " +
                          ".changes file, but is not present on disk")

  def tag_release(self):
    #TODO decide what command should be able to remove a tag notice
    info("If you are happy with the results and upload use tagdeb to tag this"
        +" release. If you do not release it...")


class DebExportUpstreamBuild(DebBuild):

  def __init__(self, properties, tree, export_upstream, export_revision,
               export_prepull, stop_on_no_change, _is_working_tree=False):
    DebBuild.__init__(self, properties, tree,
                      _is_working_tree=_is_working_tree)
    build_dir = self._properties.build_dir()
    dest = os.path.join(build_dir, self._tarball_name())
    tarball_base = self._properties.source_dir(False)
    self.exporter = UpstreamExporter(export_upstream, dest, tarball_base,
                                     export_prepull=export_prepull,
                                     export_revision=export_revision,
                                     stop_on_no_change=stop_on_no_change,
                                     )

  def _export_upstream_branch(self):
    return self.exporter.export()

  def _find_tarball(self):
    build_dir = self._properties.build_dir()
    return os.path.join(build_dir, self._tarball_name())


class DebMergeBuild(DebBuild):
  """A subclass of DebBuild that uses the merge method."""

  def _export_upstream_branch(self):
    return False

  def export(self, use_existing=False):
    package = self._properties.package()
    upstream = self._properties.upstream_version()
    build_dir = self._properties.build_dir()
    source_dir = self._properties.source_dir()
    info("Exporting to %s in merge mode", source_dir)
    if not use_existing:
      upstream = self._export_upstream_branch()
      tarball = self._find_tarball()
      mutter("Extracting %s to %s", tarball, source_dir)
      tempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)
      tar = tarfile.open(tarball)
      try:
        if getattr(tar, 'extractall', None) is not None:
          tar.extractall(tempdir)
        else:
          #Dammit, that's new in 2.5
          for tarinfo in tar.getmembers():
            if tarinfo.isdir():
              tar.extract(tarinfo, tempdir)
          for tarinfo in tar.getmembers():
            if not tarinfo.isdir():
              tar.extract(tarinfo, tempdir)
      finally:
        tar.close()
      files = glob.glob(tempdir+'/*')
      os.makedirs(source_dir)
      if len(files) == 1:
        shutil.move(files[0], source_dir)
        shutil.rmtree(tempdir)
      else:
        shutil.move(tempdir, source_dir)
      if not upstream:
        shutil.copy(tarball, build_dir)
    else:
      info("Reusing existing build dir as requested")

    info("Exporting debian/ part to %s", source_dir)
    basetempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)
    tempdir = os.path.join(basetempdir,"export")
    if self._properties.larstiq():
      os.makedirs(tempdir)
      export_dir = os.path.join(tempdir,'debian')
    else:
      export_dir = tempdir
    tree = self._tree
    tree.lock_read()
    try:
      self._prepare_working_tree()
      export(tree,export_dir,None,None)
    finally:
      tree.unlock()
    if os.path.exists(os.path.join(source_dir, 'debian')):
      shutil.rmtree(os.path.join(source_dir, 'debian'))
    recursive_copy(tempdir, source_dir)
    shutil.rmtree(basetempdir)
    if self._properties.larstiq():
        remove_bzrbuilddeb_dir(os.path.join(source_dir, "debian"))
    else:
        remove_bzrbuilddeb_dir(source_dir)

class DebNativeBuild(DebBuild):
  """A subclass of DebBuild that builds native packages."""

  def export(self, use_existing=False):
    # Just copy the tree across. use_existing makes no sense here
    # as there is no tarball.
    source_dir = self._properties.source_dir()
    info("Exporting to %s", source_dir)
    tree = self._tree
    tree.lock_read()
    try:
      self._prepare_working_tree()
      export(tree,source_dir,None,None)
    finally:
      tree.unlock()
    remove_bzrbuilddeb_dir(source_dir)

class DebSplitBuild(DebBuild):
  """A subclass of DebBuild that splits the branch to create the 
     .orig.tar.gz."""

  def export(self, use_existing=False):
    # To acheive this we export delete debian/ and tar the result,
    # then we blow that away and export the whole thing again.
    source_dir = self._properties.source_dir()
    build_dir = self._properties.build_dir()
    tarball = os.path.join(build_dir, self._tarball_name())
    tree = self._tree
    tree.lock_read()
    try:
      self._prepare_working_tree()
      export(tree,source_dir,None,None)
      info("Creating .orig.tar.gz: %s", tarball)
      remove_bzrbuilddeb_dir(source_dir)
      remove_debian_dir(source_dir)
      source_dir_rel = self._properties.source_dir(False)
      tar = tarfile.open(tarball, "w:gz")
      try:
        tar.add(source_dir, source_dir_rel)
      finally:
        tar.close()
      shutil.rmtree(source_dir)
      info("Exporting to %s", source_dir)
      self._prepare_working_tree()
      export(tree,source_dir,None,None)
    finally:
      tree.unlock()
    remove_bzrbuilddeb_dir(source_dir)

class DebMergeExportUpstreamBuild(DebMergeBuild):
  """Subclass of DebMergeBuild that will export an upstream branch to
     .orig.tar.gz before building."""

  def __init__(self, properties, tree, export_upstream, export_revision,
               export_prepull, stop_on_no_change, _is_working_tree=False):
    DebMergeBuild.__init__(self, properties, tree,
                           _is_working_tree=_is_working_tree)
    build_dir = self._properties.build_dir()
    dest = os.path.join(build_dir, self._tarball_name())
    tarball_base = self._properties.source_dir(False)
    self.exporter = UpstreamExporter(export_upstream, dest, tarball_base,
                                     export_prepull=export_prepull,
                                     export_revision=export_revision,
                                     stop_on_no_change=stop_on_no_change,
                                     )

  def _export_upstream_branch(self):
    return self.exporter.export()

  def _find_tarball(self):
    build_dir = self._properties.build_dir()
    return os.path.join(build_dir, self._tarball_name())

# vim: ts=2 sts=2 sw=2
