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

import shutil
import subprocess
import os

from bzrlib.trace import info

from bzrlib.plugins.builddeb.errors import (
                    NoSourceDirError,
                    BuildFailedError,
                    )


class DebBuild(object):
    """The object that does the building work."""

    def __init__(self, distiller, target_dir, builder, use_existing=False):
        """Create a builder.

        :param distiller: the SourceDistiller that will get the source to
            build.
        :param target_dir: the directory in which to do all the work.
        :param builder: the build command to use.
        :param use_existing: whether to re-use the target_dir if it exists.
        """
        self.distiller = distiller
        self.target_dir = target_dir
        self.builder = builder
        self.use_existing = use_existing

    def prepare(self):
        """Do any preparatory steps that should be run before the build.

        It checks that everything is well, and that some needed dirs are
        created.
        """
        parent_dir = os.path.dirname(self.target_dir)
        if os.path.basename(self.target_dir) == '':
            parent_dir = os.path.dirname(parent_dir)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        if os.path.exists(self.target_dir):
            if not self.use_existing:
                info("Purging the build dir: %s", self.target_dir)
                shutil.rmtree(self.target_dir)
            else:
                info("Not purging build dir as requested: %s",
                        self.target_dir)
        else:
            if self.use_existing:
                raise NoSourceDirError

    def export(self):
        self.distiller.distill(self.target_dir)

    def build(self):
        """This builds the package using the supplied command."""
        info("Building the package in %s, using %s", self.target_dir,
                self.builder)
        proc = subprocess.Popen(self.builder, shell=True, cwd=self.target_dir)
        proc.wait()
        if proc.returncode != 0:
            raise BuildFailedError

    def clean(self):
        """This removes the build directory."""
        info("Cleaning build dir: %s", self.target_dir)
        shutil.rmtree(self.target_dir)
