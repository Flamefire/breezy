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

from __future__ import absolute_import

import os
import sys

import bzrlib
import bzrlib.api

from bzrlib.plugins.git.info import (
    bzr_compatible_versions,
    bzr_plugin_version as version_info,
    dulwich_minimum_version,
    )

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

bzrlib.api.require_any_api(bzrlib, bzr_compatible_versions)

try:
    from bzrlib.i18n import load_plugin_translations
except ImportError: # No translations for bzr < 2.5
    gettext = lambda x: x
else:
    translation = load_plugin_translations("bzr-git")
    gettext = translation.gettext

from bzrlib import (
    errors as bzr_errors,
    trace,
    )

from bzrlib.controldir import (
    ControlDirFormat,
    Prober,
    format_registry,
    network_format_registry as controldir_network_format_registry,
    )

from bzrlib.transport import (
    register_lazy_transport,
    register_transport_proto,
    transport_server_registry,
    )
from bzrlib.commands import (
    plugin_cmds,
    )


if getattr(sys, "frozen", None):
    # allow import additional libs from ./_lib for bzr.exe only
    sys.path.append(os.path.normpath(
        os.path.join(os.path.dirname(__file__), '_lib')))


def import_dulwich():
    try:
        from dulwich import __version__ as dulwich_version
    except ImportError:
        raise bzr_errors.DependencyNotPresent("dulwich",
            "bzr-git: Please install dulwich, https://launchpad.net/dulwich")
    else:
        if dulwich_version < dulwich_minimum_version:
            raise bzr_errors.DependencyNotPresent("dulwich",
                "bzr-git: Dulwich is too old; at least %d.%d.%d is required" %
                    dulwich_minimum_version)


_versions_checked = False
def lazy_check_versions():
    global _versions_checked
    if _versions_checked:
        return
    import_dulwich()
    _versions_checked = True

format_registry.register_lazy('git',
    "bzrlib.plugins.git.dir", "LocalGitControlDirFormat",
    help='GIT repository.', native=False, experimental=False,
    )

format_registry.register_lazy('git-bare',
    "bzrlib.plugins.git.dir", "BareLocalGitControlDirFormat",
    help='Bare GIT repository (no working tree).', native=False,
    experimental=False,
    )

from bzrlib.revisionspec import (RevisionSpec_dwim, revspec_registry)
revspec_registry.register_lazy("git:", "bzrlib.plugins.git.revspec",
    "RevisionSpec_git")
RevisionSpec_dwim.append_possible_lazy_revspec(
    "bzrlib.plugins.git.revspec", "RevisionSpec_git")


class LocalGitProber(Prober):

    def probe_transport(self, transport):
        try:
            external_url = transport.external_url()
        except bzr_errors.InProcessTransport:
            raise bzr_errors.NotBranchError(path=transport.base)
        if (external_url.startswith("http:") or
            external_url.startswith("https:")):
            # Already handled by RemoteGitProber
            raise bzr_errors.NotBranchError(path=transport.base)
        from bzrlib import urlutils
        if urlutils.split(transport.base)[1] == ".git":
            raise bzr_errors.NotBranchError(path=transport.base)
        if not transport.has_any(['objects', '.git/objects']):
            raise bzr_errors.NotBranchError(path=transport.base)
        lazy_check_versions()
        from bzrlib.plugins.git.dir import (
            BareLocalGitControlDirFormat,
            LocalGitControlDirFormat,
            )
        if transport.has_any(['.git/objects']):
            return LocalGitControlDirFormat()
        if transport.has('info') and transport.has('objects'):
            return BareLocalGitControlDirFormat()
        raise bzr_errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        from bzrlib.plugins.git.dir import (
            BareLocalGitControlDirFormat,
            LocalGitControlDirFormat,
            )
        return set([BareLocalGitControlDirFormat(), LocalGitControlDirFormat()])


class RemoteGitProber(Prober):

    def probe_http_transport(self, transport):
        from bzrlib import urlutils
        base_url, _ = urlutils.split_segment_parameters(transport.external_url())
        url = urlutils.join(base_url, "info/refs") + "?service=git-upload-pack"
        from bzrlib.transport.http._urllib import HttpTransport_urllib, Request
        if isinstance(transport, HttpTransport_urllib):
            req = Request('GET', url, accepted_errors=[200, 403, 404, 405],
                          headers={"Content-Type": "application/x-git-upload-pack-request"})
            req.follow_redirections = True
            resp = transport._perform(req)
            if resp.code in (404, 405):
                raise bzr_errors.NotBranchError(transport.base)
            headers = resp.headers
            refs_text = resp.read()
        else:
            try:
                from bzrlib.transport.http._pycurl import PyCurlTransport
            except bzr_errors.DependencyNotPresent:
                raise bzr_errors.NotBranchError(transport.base)
            else:
                import pycurl
                from cStringIO import StringIO
                if isinstance(transport, PyCurlTransport):
                    conn = transport._get_curl()
                    conn.setopt(pycurl.URL, url)
                    conn.setopt(pycurl.FOLLOWLOCATION, 1)
                    transport._set_curl_options(conn)
                    conn.setopt(pycurl.HTTPGET, 1)
                    header = StringIO()
                    data = StringIO()
                    conn.setopt(pycurl.HEADERFUNCTION, header.write)
                    conn.setopt(pycurl.WRITEFUNCTION, data.write)
                    transport._curl_perform(conn, header,
                        ["Content-Type: application/x-git-upload-pack-request"])
                    code = conn.getinfo(pycurl.HTTP_CODE)
                    if code in (404, 405):
                        raise bzr_errors.NotBranchError(transport.base)
                    if code != 200:
                        raise bzr_errors.InvalidHttpResponse(transport._path,
                            str(code))
                    headers = transport._parse_headers(header)
                else:
                    raise bzr_errors.NotBranchError(transport.base)
                refs_text = data.getvalue()
        ct = headers.getheader("Content-Type")
        if ct is None:
            raise bzr_errors.NotBranchError(transport.base)
        if ct.startswith("application/x-git"):
            from bzrlib.plugins.git.remote import RemoteGitControlDirFormat
            return RemoteGitControlDirFormat()
        else:
            from bzrlib.plugins.git.dir import (
                BareLocalGitControlDirFormat,
                )
            ret = BareLocalGitControlDirFormat()
            ret._refs_text = refs_text
            return ret

    def probe_transport(self, transport):
        try:
            external_url = transport.external_url()
        except bzr_errors.InProcessTransport:
            raise bzr_errors.NotBranchError(path=transport.base)

        if (external_url.startswith("http:") or
            external_url.startswith("https:")):
            return self.probe_http_transport(transport)

        if (not external_url.startswith("git://") and
            not external_url.startswith("git+")):
            raise bzr_errors.NotBranchError(transport.base)

        # little ugly, but works
        from bzrlib.plugins.git.remote import (
            GitSmartTransport,
            RemoteGitControlDirFormat,
            )
        if isinstance(transport, GitSmartTransport):
            return RemoteGitControlDirFormat()
        raise bzr_errors.NotBranchError(path=transport.base)

    @classmethod
    def known_formats(cls):
        from bzrlib.plugins.git.remote import RemoteGitControlDirFormat
        return set([RemoteGitControlDirFormat()])


ControlDirFormat.register_prober(LocalGitProber)
ControlDirFormat._server_probers.append(RemoteGitProber)

register_transport_proto('git://',
        help="Access using the Git smart server protocol.")
register_transport_proto('git+ssh://',
        help="Access using the Git smart server protocol over SSH.")

register_lazy_transport("git://", 'bzrlib.plugins.git.remote',
                        'TCPGitSmartTransport')
register_lazy_transport("git+ssh://", 'bzrlib.plugins.git.remote',
                        'SSHGitSmartTransport')


plugin_cmds.register_lazy("cmd_git_import", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_object", ["git-objects", "git-cat"],
    "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_refs", [], "bzrlib.plugins.git.commands")
plugin_cmds.register_lazy("cmd_git_apply", [], "bzrlib.plugins.git.commands")

def extract_git_foreign_revid(rev):
    try:
        foreign_revid = rev.foreign_revid
    except AttributeError:
        from bzrlib.plugins.git.mapping import mapping_registry
        foreign_revid, mapping = \
            mapping_registry.parse_revision_id(rev.revision_id)
        return foreign_revid
    else:
        from bzrlib.plugins.git.mapping import foreign_vcs_git
        if rev.mapping.vcs == foreign_vcs_git:
            return foreign_revid
        else:
            raise bzr_errors.InvalidRevisionId(rev.revision_id, None)


def update_stanza(rev, stanza):
    mapping = getattr(rev, "mapping", None)
    try:
        git_commit = extract_git_foreign_revid(rev)
    except bzr_errors.InvalidRevisionId:
        pass
    else:
        stanza.add("git-commit", git_commit)

from bzrlib.hooks import install_lazy_named_hook
install_lazy_named_hook("bzrlib.version_info_formats.format_rio",
    "RioVersionInfoBuilder.hooks", "revision", update_stanza,
    "git commits")


transport_server_registry.register_lazy('git',
    'bzrlib.plugins.git.server',
    'serve_git',
    'Git Smart server protocol over TCP. (default port: 9418)')

transport_server_registry.register_lazy('git-receive-pack',
    'bzrlib.plugins.git.server',
    'serve_git_receive_pack',
    help='Git Smart server receive pack command. (inetd mode only)')
transport_server_registry.register_lazy('git-upload-pack',
    'bzrlib.plugins.git.server',
    'serve_git_upload_pack',
    help='Git Smart server upload pack command. (inetd mode only)')

from bzrlib.repository import (
    format_registry as repository_format_registry,
    network_format_registry as repository_network_format_registry,
    )
repository_network_format_registry.register_lazy('git',
    'bzrlib.plugins.git.repository', 'GitRepositoryFormat')

register_extra_lazy_repository_format = getattr(repository_format_registry,
    "register_extra_lazy")
register_extra_lazy_repository_format('bzrlib.plugins.git.repository',
    'GitRepositoryFormat')

from bzrlib.branch import (
    network_format_registry as branch_network_format_registry,
    )
branch_network_format_registry.register_lazy('git',
    'bzrlib.plugins.git.branch', 'GitBranchFormat')

from bzrlib.branch import (
    format_registry as branch_format_registry,
    )
branch_format_registry.register_extra_lazy(
    'bzrlib.plugins.git.branch',
    'GitBranchFormat',
    )

from bzrlib.workingtree import (
    format_registry as workingtree_format_registry,
    )
workingtree_format_registry.register_extra_lazy(
    'bzrlib.plugins.git.workingtree',
    'GitWorkingTreeFormat',
    )

controldir_network_format_registry.register_lazy('git',
    "bzrlib.plugins.git.dir", "GitControlDirFormat")


try:
    from bzrlib.registry import register_lazy
except ImportError:
    from bzrlib.diff import format_registry as diff_format_registry
    diff_format_registry.register_lazy('git', 'bzrlib.plugins.git.send',
        'GitDiffTree', 'Git am-style diff format')

    from bzrlib.send import (
        format_registry as send_format_registry,
        )
    send_format_registry.register_lazy('git', 'bzrlib.plugins.git.send',
                                       'send_git', 'Git am-style diff format')

    from bzrlib.directory_service import directories
    directories.register_lazy('github:', 'bzrlib.plugins.git.directory',
                              'GitHubDirectory',
                              'GitHub directory.')
    directories.register_lazy('git@github.com:', 'bzrlib.plugins.git.directory',
                              'GitHubDirectory',
                              'GitHub directory.')

    from bzrlib.help_topics import (
        topic_registry,
        )
    topic_registry.register_lazy('git', 'bzrlib.plugins.git.help', 'help_git',
        'Using Bazaar with Git')

    from bzrlib.foreign import (
        foreign_vcs_registry,
        )
    foreign_vcs_registry.register_lazy("git",
        "bzrlib.plugins.git.mapping", "foreign_vcs_git", "Stupid content tracker")
else:
    register_lazy("bzrlib.diff", "format_registry",
        'git', 'bzrlib.plugins.git.send', 'GitDiffTree',
        'Git am-style diff format')
    register_lazy("bzrlib.send", "format_registry",
        'git', 'bzrlib.plugins.git.send', 'send_git',
        'Git am-style diff format')
    register_lazy('bzrlib.directory_service', 'directories', 'github:',
            'bzrlib.plugins.git.directory', 'GitHubDirectory',
            'GitHub directory.')
    register_lazy('bzrlib.directory_service', 'directories',
            'git@github.com:', 'bzrlib.plugins.git.directory',
            'GitHubDirectory', 'GitHub directory.')
    register_lazy('bzrlib.help_topics', 'topic_registry',
            'git', 'bzrlib.plugins.git.help', 'help_git',
            'Using Bazaar with Git')
    register_lazy('bzrlib.foreign', 'foreign_vcs_registry', "git",
        "bzrlib.plugins.git.mapping", "foreign_vcs_git", "Stupid content tracker")

def update_git_cache(repository, revid):
    """Update the git cache after a local commit."""
    if getattr(repository, "_git", None) is not None:
        return # No need to update cache for git repositories

    if not repository.control_transport.has("git"):
        return # No existing cache, don't bother updating
    try:
        lazy_check_versions()
    except bzr_errors.DependencyNotPresent, e:
        # dulwich is probably missing. silently ignore
        trace.mutter("not updating git map for %r: %s",
            repository, e)

    from bzrlib.plugins.git.object_store import BazaarObjectStore
    store = BazaarObjectStore(repository)
    store.lock_write()
    try:
        try:
            parent_revisions = set(repository.get_parent_map([revid])[revid])
        except KeyError:
            # Isn't this a bit odd - how can a revision that was just committed be missing?
            return
        missing_revisions = store._missing_revisions(parent_revisions)
        if not missing_revisions:
            # Only update if the cache was up to date previously
            store._update_sha_map_revision(revid)
    finally:
        store.unlock()


def post_commit_update_cache(local_branch, master_branch, old_revno, old_revid,
        new_revno, new_revid):
    if local_branch is not None:
        update_git_cache(local_branch.repository, new_revid)
    update_git_cache(master_branch.repository, new_revid)


def loggerhead_git_hook(branch_app, environ):
    branch = branch_app.branch
    config_stack = branch.get_config_stack()
    if config_stack.get('http_git'):
        return None
    from bzrlib.plugins.git.server import git_http_hook
    return git_http_hook(branch, environ['REQUEST_METHOD'],
        environ['PATH_INFO'])

install_lazy_named_hook("bzrlib.branch",
    "Branch.hooks", "post_commit", post_commit_update_cache,
    "git cache")
install_lazy_named_hook("bzrlib.plugins.loggerhead.apps.branch",
    "BranchWSGIApp.hooks", "controller",
    loggerhead_git_hook, "git support")


from bzrlib.config import (
    option_registry,
    Option,
    bool_from_store,
    )

option_registry.register(
    Option('git.http',
           default=None, from_unicode=bool_from_store, invalid='warning',
           help='''\
Allow fetching of Git packs over HTTP.

This enables support for fetching Git packs over HTTP in Loggerhead.
'''))

def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
