# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""A grouping of Exceptions for bzr-git"""


from dulwich import errors as git_errors

from dulwich.errors import NotCommitError

from bzrlib import errors as bzr_errors


class BzrGitError(bzr_errors.BzrError):
    """The base-level exception for bzr-git errors."""


class NoSuchRef(BzrGitError):
    """Raised when a ref can not be found."""

    _fmt = "The ref %(ref)s was not found in the repository at %(location)s."

    def __init__(self, ref, location, present_refs=None):
        self.ref = ref
        self.location = location
        self.present_refs = present_refs


def convert_dulwich_error(error):
    """Convert a Dulwich error to a Bazaar error."""

    if isinstance(error, git_errors.HangupException):
        raise bzr_errors.ConnectionReset(error.msg, "")
    raise error


class NoPushSupport(bzr_errors.BzrError):
    _fmt = "Push is not yet supported for bzr-git. Try dpush instead."


class GitSmartRemoteNotSupported(bzr_errors.UnsupportedOperation):
    _fmt = "This operation is not supported by the Git smart server protocol."
