#    errors.py -- Error classes
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

from bzrlib.errors import BzrError


class DebianError(BzrError):
  _fmt = """A Debian packaging error occurred: %(message)s"""

  def __init__(self, message):
    BzrError.__init__(self)
    self.message = message

class NoSourceDirError(DebianError):
  _fmt = """There is no existing source directory to use. Use --export-only or 
  --dont-purge to get one that can be used"""

  def __init__(self):
    DebianError.__init__(self, None)

class BuildFailedError(DebianError):
  _fmt = """The build failed."""
  def __init__(self):
    DebianError.__init__(self, None)

class StopBuild(DebianError):
  _fmt = """Stopping the build: %(reason)s."""

  def __init__(self, reason):
    BzrError.__init__(self)
    self.reason = reason

class MissingChangelogError(DebianError):
  _fmt = """Could not find changelog at %(location)s."""

  def __init__(self, locations):
    BzrError.__init__(self)
    self.location = locations

class AddChangelogError(DebianError):
  _fmt = """Please add %(changelog)s to the branch using bzr add."""

  def __init__(self, changelog):
    BzrError.__init__(self)
    self.changelog = changelog

class ImportError(DebianError):
  _fmt = """The files could not be imported: %(reason)s"""

  def __init__(self, reason):
    BzrError.__init__(self)
    self.reason = reason

class HookFailedError(BzrError):
  _fmt = """The %(hook_name)s hook failed."""

  def __init__(self, hook_name):
    BzrError.__init__(self)
    self.hook_name = hook_name


class OnlyImportSingleDsc(BzrError):
  _fmt = """You are only allowed to import one version in incremental mode."""

class UnknownType(BzrError):
  _fmt = """Cannot extract "%(path)s" from archive as it is an unknown type."""

  def __init__(self, path):
    self.path = path


class MissingChanges(BzrError):
  _fmt = """Could not find .changes file: %(changes)s."""

  def __init__(self, changes):
    self.changes = changes


# vim: ts=2 sts=2 sw=2
