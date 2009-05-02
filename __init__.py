# Copyright (C) 2006-2009 Canonical Ltd

# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer@samba.org>
#          John Carr <john.carr@unrouted.co.uk>
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


"""A GIT branch and repository format implementation for bzr."""

import os
import sys

import bzrlib
import bzrlib.api
from bzrlib import (
    bzrdir,
    errors as bzr_errors,
    osutils,
    )
from bzrlib.foreign import (
    foreign_vcs_registry,
    )
from bzrlib.lockable_files import (
    TransportLock,
    )
from bzrlib.transport import (
    register_lazy_transport,
    register_transport_proto,
    )
from bzrlib.commands import (
    plugin_cmds,
    )
from bzrlib.trace import (
    warning,
    )
from bzrlib.version_info_formats.format_rio import (
    RioVersionInfoBuilder,
    )


# versions ending in 'exp' mean experimental mappings
# versions ending in 'dev' mean development version
# versions ending in 'final' mean release (well tested, etc)
version_info = (0, 2, 2, 'dev', 0)

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

MINIMUM_DULWICH_VERSION = (0, 2, 0)
COMPATIBLE_BZR_VERSIONS = [(1, 14, 0), (1, 15, 0)]

if getattr(sys, "frozen", None):
    # allow import additional libs from ./_lib for bzr.exe only
    sys.path.append(os.path.normpath(os.path.join(os.path.dirname(__file__), '_lib')))

_versions_checked = False
def lazy_check_versions():
    global _versions_checked
    if _versions_checked:
        return
    _versions_checked = True
    try:
        from dulwich import __version__ as dulwich_version
    except ImportError:
        raise ImportError("bzr-git: Please install dulwich, https://launchpad.net/dulwich")
    else:
        if dulwich_version < MINIMUM_DULWICH_VERSION:
            raise ImportError("bzr-git: Dulwich is too old; at least %d.%d.%d is required" % MINIMUM_DULWICH_VERSION)

bzrlib.api.require_any_api(bzrlib, COMPATIBLE_BZR_VERSIONS)

bzrdir.format_registry.register_lazy('git', 
    "bzrlib.plugins.git.dir", "LocalGitBzrDirFormat",
    help='GIT repository.', native=False, experimental=True,
    )

from bzrlib.revisionspec import revspec_registry
revspec_registry.register_lazy("git:", "bzrlib.plugins.git.revspec", 
    "RevisionSpec_git")


class GitBzrDirFormat(bzrdir.BzrDirFormat):
    _lock_class = TransportLock

    def is_supported(self):
        return True


class LocalGitBzrDirFormat(GitBzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([LocalGitBzrDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        import dulwich as git
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]

        try:
            gitrepo = git.repo.Repo(transport.local_abspath(".").encode(osutils._fs_enc))
        except bzr_errors.NotLocalUrl:
            raise bzr_errors.NotBranchError(path=transport.base)
        from bzrlib.plugins.git.dir import LocalGitDir, GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return LocalGitDir(transport, lockfiles, gitrepo, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        from bzrlib.transport.local import LocalTransport

        if not isinstance(transport, LocalTransport):
            raise bzr_errors.NotBranchError(path=transport.base)

        # This should quickly filter out most things that are not 
        # git repositories, saving us the trouble from loading dulwich.
        if not transport.has(".git") and not transport.has("objects"):
            raise bzr_errors.NotBranchError(path=transport.base)

        import dulwich as git
        format = klass()
        try:
            format.open(transport)
            return format
        except git.errors.NotGitRepository, e:
            raise bzr_errors.NotBranchError(path=transport.base)
        raise bzr_errors.NotBranchError(path=transport.base)

    def get_format_description(self):
        return "Local Git Repository"

    def get_format_string(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        from bzrlib.transport.local import LocalTransport

        if not isinstance(transport, LocalTransport):
            raise NotImplementedError(self.initialize, 
                "Can't create Git Repositories/branches on "
                "non-local transports")

        from dulwich.repo import Repo
        Repo.create(transport.local_abspath(".").encode(osutils._fs_enc)) 
        return self.open(transport)

    def is_supported(self):
        return True


class RemoteGitBzrDirFormat(GitBzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([RemoteGitBzrDirFormat()])

    def open(self, transport, _found=None):
        """Open this directory.

        """
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if (not url.startswith("git://") and 
            not url.startswith("git+")):
            raise bzr_errors.NotBranchError(transport.base)
        from bzrlib.plugins.git.remote import RemoteGitDir, GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        from bzrlib.plugins.git.dir import GitLockableFiles, GitLock
        lockfiles = GitLockableFiles(transport, GitLock())
        return RemoteGitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if (not url.startswith("git://") and 
            not url.startswith("git+")):
            raise bzr_errors.NotBranchError(transport.base)
        # little ugly, but works
        format = klass()
        from bzrlib.plugins.git.remote import GitSmartTransport
        if not isinstance(transport, GitSmartTransport):
            raise bzr_errors.NotBranchError(transport.base)
        # The only way to know a path exists and contains a valid repository 
        # is to do a request against it:
        try:
            transport.fetch_pack(lambda x: [], None, lambda x: None, 
                                 lambda x: mutter("git: %s" % x))
        except errors.git_errors.GitProtocolError:
            raise bzr_errors.NotBranchError(path=transport.base)
        else:
            return format
        raise bzr_errors.NotBranchError(path=transport.base)

    def get_format_description(self):
        return "Remote Git Repository"

    def get_format_string(self):
        return "Remote Git Repository"

    def initialize_on_transport(self, transport):
        raise bzr_errors.UninitializableFormat(self)


bzrdir.BzrDirFormat.register_control_format(LocalGitBzrDirFormat)
bzrdir.BzrDirFormat.register_control_format(RemoteGitBzrDirFormat)

register_transport_proto('git://', 
        help="Access using the Git smart server protocol.")
register_transport_proto('git+ssh://', 
        help="Access using the Git smart server protocol over SSH.")

register_lazy_transport("git://", 'bzrlib.plugins.git.remote',
                        'TCPGitSmartTransport')
register_lazy_transport("git+ssh://", 'bzrlib.plugins.git.remote',
                        'SSHGitSmartTransport')

foreign_vcs_registry.register_lazy("git", 
    "bzrlib.plugins.git.mapping", "foreign_git", "Stupid content tracker")

plugin_cmds.register_lazy("cmd_git_serve", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_import", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_cat", [], "bzrlib.plugins.git.commands")

def update_stanza(rev, stanza):
    mapping = getattr(rev, "mapping", None)
    if mapping is not None and mapping.revid_prefix.startswith("git-"):
        stanza.add("git-commit", rev.foreign_revid)


rio_hooks = getattr(RioVersionInfoBuilder, "hooks", None)
if rio_hooks is not None:
    rio_hooks.install_named_hook('revision', update_stanza, None)

def get_rich_root_format(stacked=False):
    if stacked:
        return bzrdir.format_registry.make_bzrdir("1.9-rich-root")
    else:
        return bzrdir.format_registry.make_bzrdir("default-rich-root")

def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
