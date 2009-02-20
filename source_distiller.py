#    source_distiller.py -- Getting the source to build from a branch
#    Copyright (C) 2008, 2009 Canonical Ltd.
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

import glob
import os
import shutil
import subprocess
import tempfile

from bzrlib import errors as bzr_errors
from bzrlib.export import export

from bzrlib.plugins.builddeb.errors import (
        TarFailed,
        )
from bzrlib.plugins.builddeb.util import recursive_copy


class SourceDistiller(object):
    """A source distiller extracts the source to build from a location.

    It does whatever is needed to give you a source you can build at
    a location of your choice.
    """

    supports_use_existing = False

    def __init__(self, tree, upstream_provider, larstiq=False,
            use_existing=False):
        """Create a SourceDistiller to distill from the specified tree.

        :param tree: The tree to use as the source.
        :param upstream_provider: an UpstreamProvider to provide the upstream
            tarball if needed.
        :param larstiq: if the tree is in the "LarstiQ" layout.
        :param use_existing: whether the distiller should re-use an existing
            target if the distiller supports it.
        """
        self.tree = tree
        self.upstream_provider = upstream_provider
        self.larstiq = larstiq
        self.use_existing = use_existing
        if not self.supports_use_existing:
            assert not self.use_existing, "distiller doesn't support use_existing"

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to 
            place the tree containing the buildable source.
        """
        if not self.supports_use_existing or not self.use_existing:
            if os.path.exists(target):
                raise bzr_errors.FileExists(target)
        elif self.supports_use_existing and self.use_existing:
            if not os.path.exists(target):
                raise bzr_errors.NotADirectory(target)
        self._distill(target)

    def _distill(self, target):
        """Subclasses should override this to implement distill."""
        raise NotImplementedError(self._distill)


class NativeSourceDistiller(SourceDistiller):
    """A SourceDistiller for unpacking a native package from a branch."""

    def _distill(self, target):
        export(self.tree, target, None, None)


class FullSourceDistiller(SourceDistiller):
    """A SourceDistiller for full-source branches, a.k.a. normal mode"""

    def _distill(self, target):
        parent_dir = os.path.dirname(target)
        self.upstream_provider.provide(parent_dir)
        export(self.tree, target, None, None)


class MergeModeDistiller(SourceDistiller):

    supports_use_existing = True

    def _distill(self, target):
        # Get the upstream tarball
        parent_dir = os.path.dirname(target)
        if os.path.basename(target) == '':
            parent_dir = os.path.dirname(parent_dir)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        if not self.use_existing:
            tarball = self.upstream_provider.provide(parent_dir)
            # Extract it to the right place
            tempdir = tempfile.mkdtemp(prefix='builddeb-merge-')
            try:
                ret = subprocess.call(['tar','-C',tempdir,'-xf',tarball])
                if ret != 0:
                    raise TarFailed("uncompress", tarball)
                files = glob.glob(tempdir+'/*')
                # If everything is in a single dir then move everything up one
                # level.
                if len(files) == 1:
                    shutil.move(files[0], target)
                else:
                    shutil.move(tempdir, target)
            finally:
                if os.path.exists(tempdir):
                    shutil.rmtree(tempdir)
        # Now export the tree to provide the debian dir
        basetempdir = tempfile.mkdtemp(prefix='builddeb-merge-debian-')
        try:
            tempdir = os.path.join(basetempdir,"export")
            if self.larstiq:
                os.makedirs(tempdir)
                export_dir = os.path.join(tempdir,'debian')
            else:
                export_dir = tempdir
            export(self.tree,export_dir,None,None)
            # Remove any upstream debian dir, or from previous export with
            # use_existing
            if os.path.exists(os.path.join(target, 'debian')):
                shutil.rmtree(os.path.join(target, 'debian'))
            recursive_copy(tempdir, target)
        finally:
            shutil.rmtree(basetempdir)
