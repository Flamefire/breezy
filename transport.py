# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Simple transport for accessing Subversion smart servers."""

from bzrlib import debug, urlutils
from bzrlib.errors import (NoSuchFile, NotBranchError, TransportNotPossible, 
                           FileExists, NotLocalUrl, InvalidURL)
from bzrlib.trace import mutter
from bzrlib.transport import Transport

from svn.core import SubversionException, Pool
import svn.ra
import svn.core
import svn.client

from errors import convert_svn_error, NoSvnRepositoryPresent
import urlparse
import urllib

svn_config = svn.core.svn_config_get_config(None)

def get_client_string():
    """Return a string that can be send as part of the User Agent string."""
    return "bzr%s+bzr-svn%s" % (bzrlib.__version__, bzrlib.plugins.svn.__version__)

 
def create_svn_client(url):
    from auth import create_auth_baton
    client = svn.client.create_context()
    client.auth_baton = create_auth_baton(url)
    client.config = svn_config
    return client


# Don't run any tests on SvnTransport as it is not intended to be 
# a full implementation of Transport
def get_test_permutations():
    return []


def get_svn_ra_transport(bzr_transport):
    """Obtain corresponding SvnRaTransport for a stock Bazaar transport."""
    if isinstance(bzr_transport, SvnRaTransport):
        return bzr_transport

    return SvnRaTransport(bzr_transport.base)


def _url_unescape_uri(url):
    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
    path = urllib.unquote(path)
    return urlparse.urlunsplit((scheme, netloc, path, query, fragment))


def bzr_to_svn_url(url):
    """Convert a Bazaar URL to a URL understood by Subversion.

    This will possibly remove the svn+ prefix.
    """
    if (url.startswith("svn+http://") or 
        url.startswith("svn+file://") or
        url.startswith("svn+https://")):
        url = url[len("svn+"):] # Skip svn+

    if url.startswith("http"):
        # Without this, URLs with + in them break
        url = _url_unescape_uri(url)

    # The SVN libraries don't like trailing slashes...
    url = url.rstrip('/')

    return url


def needs_busy(unbound):
    """Decorator that marks a transport as busy before running a methd on it.
    """
    def convert(self, *args, **kwargs):
        self._mark_busy()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self._unmark_busy()

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert


class Editor(object):
    """Simple object wrapper around the Subversion delta editor interface."""
    def __init__(self, transport, (editor, editor_baton)):
        self.editor = editor
        self.editor_baton = editor_baton
        self.recent_baton = []
        self._transport = transport

    @convert_svn_error
    def open_root(self, base_revnum):
        assert self.recent_baton == [], "root already opened"
        baton = svn.delta.editor_invoke_open_root(self.editor, 
                self.editor_baton, base_revnum)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def close_directory(self, baton, *args, **kwargs):
        assert self.recent_baton.pop() == baton, \
                "only most recently opened baton can be closed"
        svn.delta.editor_invoke_close_directory(self.editor, baton, *args, **kwargs)

    @convert_svn_error
    def close(self):
        assert self.recent_baton == []
        svn.delta.editor_invoke_close_edit(self.editor, self.editor_baton)
        self._transport._unmark_busy()

    @convert_svn_error
    def apply_textdelta(self, baton, *args, **kwargs):
        assert self.recent_baton[-1] == baton
        return svn.delta.editor_invoke_apply_textdelta(self.editor, baton,
                *args, **kwargs)

    @convert_svn_error
    def change_dir_prop(self, baton, name, value, pool=None):
        assert self.recent_baton[-1] == baton
        return svn.delta.editor_invoke_change_dir_prop(self.editor, baton, 
                                                       name, value, pool)

    @convert_svn_error
    def delete_entry(self, *args, **kwargs):
        return svn.delta.editor_invoke_delete_entry(self.editor, *args, **kwargs)

    @convert_svn_error
    def add_file(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_add_file(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def open_file(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_open_file(self.editor, path, 
                                                 parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def change_file_prop(self, baton, name, value, pool=None):
        assert self.recent_baton[-1] == baton
        svn.delta.editor_invoke_change_file_prop(self.editor, baton, name, 
                                                 value, pool)

    @convert_svn_error
    def close_file(self, baton, *args, **kwargs):
        assert self.recent_baton.pop() == baton
        svn.delta.editor_invoke_close_file(self.editor, baton, *args, **kwargs)

    @convert_svn_error
    def add_directory(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_add_directory(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton

    @convert_svn_error
    def open_directory(self, path, parent_baton, *args, **kwargs):
        assert self.recent_baton[-1] == parent_baton
        baton = svn.delta.editor_invoke_open_directory(self.editor, path, 
            parent_baton, *args, **kwargs)
        self.recent_baton.append(baton)
        return baton


class Connection:
    """An single connection to a Subversion repository. This usually can 
    only do one operation at a time."""
    def __init__(self, url):
        self._busy = False
        self._root = None
        self._client = create_svn_client(url)
        try:
            self.mutter('opening SVN RA connection to %r' % url)
            self._ra = svn.client.open_ra_session(url.encode('utf8'), 
                    self._client)
        except SubversionException, (_, num):
            if num in (svn.core.SVN_ERR_RA_SVN_REPOS_NOT_FOUND,):
                raise NoSvnRepositoryPresent(url=url)
            if num == svn.core.SVN_ERR_BAD_URL:
                raise InvalidURL(url)
            raise
        self.url = url

    class Reporter(object):
        def __init__(self, transport, (reporter, report_baton)):
            self._reporter = reporter
            self._baton = report_baton
            self._transport = transport

        @convert_svn_error
        def set_path(self, path, revnum, start_empty, lock_token, pool=None):
            svn.ra.reporter2_invoke_set_path(self._reporter, self._baton, 
                        path, revnum, start_empty, lock_token, pool)

        @convert_svn_error
        def delete_path(self, path, pool=None):
            svn.ra.reporter2_invoke_delete_path(self._reporter, self._baton,
                    path, pool)

        @convert_svn_error
        def link_path(self, path, url, revision, start_empty, lock_token, 
                      pool=None):
            svn.ra.reporter2_invoke_link_path(self._reporter, self._baton,
                    path, url, revision, start_empty, lock_token,
                    pool)

        @convert_svn_error
        def finish_report(self, pool=None):
            svn.ra.reporter2_invoke_finish_report(self._reporter, 
                    self._baton, pool)
            self._transport._unmark_busy()

        @convert_svn_error
        def abort_report(self, pool=None):
            svn.ra.reporter2_invoke_abort_report(self._reporter, 
                    self._baton, pool)
            self._transport._unmark_busy()

    def is_busy(self):
        return self._busy

    def _mark_busy(self):
        assert not self._busy
        self._busy = True

    def _unmark_busy(self):
        assert self._busy
        self._busy = False

    def mutter(self, text):
        if 'transport' in debug.debug_flags:
            mutter(text)

    @convert_svn_error
    @needs_busy
    def get_uuid(self):
        self.mutter('svn get-uuid')
        return svn.ra.get_uuid(self._ra)

    @convert_svn_error
    @needs_busy
    def get_repos_root(self):
        if self._root is None:
            self.mutter("svn get-repos-root")
            self._root = svn.ra.get_repos_root(self._ra)
        return self._root

    @convert_svn_error
    @needs_busy
    def get_latest_revnum(self):
        self.mutter("svn get-latest-revnum")
        return svn.ra.get_latest_revnum(self._ra)

    def _make_editor(self, editor, pool=None):
        edit, edit_baton = svn.delta.make_editor(editor, pool)
        self._edit = edit
        self._edit_baton = edit_baton
        return self._edit, self._edit_baton

    @convert_svn_error
    def do_switch(self, switch_rev, recurse, switch_url, editor, pool=None):
        self.mutter('svn switch -r %d -> %r' % (switch_rev, switch_url))
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor, pool)
        return self.Reporter(self, svn.ra.do_switch(self._ra, switch_rev, "", 
                             recurse, switch_url, edit, edit_baton, pool))

    @convert_svn_error
    def change_rev_prop(self, revnum, name, value, pool=None):
        self.mutter('svn revprop -r%d --set %s=%s' % (revnum, name, value))
        svn.ra.change_rev_prop(self._ra, revnum, name, value)

    @convert_svn_error
    @needs_busy
    def get_lock(self, path):
        return svn.ra.get_lock(self._ra, path)

    @convert_svn_error
    @needs_busy
    def unlock(self, locks, break_lock=False):
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            pass
        return svn.ra.unlock(self._ra, locks, break_lock, lock_cb)
 
    @convert_svn_error
    @needs_busy
    def get_dir(self, path, revnum, pool=None, kind=False):
        self.mutter("svn ls -r %d '%r'" % (revnum, path))
        assert len(path) == 0 or path[0] != "/"
        # ra_dav backends fail with strange errors if the path starts with a 
        # slash while other backends don't.
        if hasattr(svn.ra, 'get_dir2'):
            fields = 0
            if kind:
                fields += svn.core.SVN_DIRENT_KIND
            return svn.ra.get_dir2(self._ra, path, revnum, fields)
        else:
            return svn.ra.get_dir(self._ra, path, revnum)

    @convert_svn_error
    @needs_busy
    def check_path(self, path, revnum):
        assert len(path) == 0 or path[0] != "/"
        self.mutter("svn check_path -r%d %s" % (revnum, path))
        return svn.ra.check_path(self._ra, path.encode('utf-8'), revnum)

    @convert_svn_error
    @needs_busy
    def mkdir(self, relpath, mode=None):
        assert len(relpath) == 0 or relpath[0] != "/"
        path = urlutils.join(self.url, relpath)
        try:
            svn.client.mkdir([path.encode("utf-8")], self._client)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_FOUND:
                raise NoSuchFile(path)
            if num == svn.core.SVN_ERR_FS_ALREADY_EXISTS:
                raise FileExists(path)
            raise

    @convert_svn_error
    def replay(self, revision, low_water_mark, send_deltas, editor, pool=None):
        self.mutter('svn replay -r%r:%r' % (low_water_mark, revision))
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor, pool)
        svn.ra.replay(self._ra, revision, low_water_mark, send_deltas,
                      edit, edit_baton, pool)

    @convert_svn_error
    def do_update(self, revnum, recurse, editor, pool=None):
        self.mutter('svn update -r %r' % revnum)
        self._mark_busy()
        edit, edit_baton = self._make_editor(editor, pool)
        return self.Reporter(self, svn.ra.do_update(self._ra, revnum, "", 
                             recurse, edit, edit_baton, pool))

    @convert_svn_error
    def has_capability(self, cap):
        return svn.ra.has_capability(self._ra, cap)

    @convert_svn_error
    def revprop_list(self, revnum, pool=None):
        self.mutter('svn revprop-list -r %r' % revnum)
        return svn.ra.rev_proplist(self._ra, revnum, pool)

    @convert_svn_error
    def get_commit_editor(self, revprops, done_cb, lock_token, keep_locks):
        self._mark_busy()
        try:
            if hasattr(svn.ra, 'get_commit_editor3'):
                editor = svn.ra.get_commit_editor3(self._ra, revprops, done_cb, 
                                                  lock_token, keep_locks)
            elif revprops.keys() != [svn.core.SVN_PROP_REVISION_LOG]:
                raise NotImplementedError()
            else:
                editor = svn.ra.get_commit_editor2(self._ra, 
                            revprops[svn.core.SVN_PROP_REVISION_LOG],
                            done_cb, lock_token, keep_locks)

            return Editor(self, editor)
        except:
            self._unmark_busy()
            raise

    class SvnLock(object):
        def __init__(self, transport, tokens):
            self._tokens = tokens
            self._transport = transport

        def unlock(self):
            self.transport.unlock(self.locks)

    @convert_svn_error
    @needs_busy
    def lock_write(self, path_revs, comment=None, steal_lock=False):
        tokens = {}
        def lock_cb(baton, path, do_lock, lock, ra_err, pool):
            tokens[path] = lock
        svn.ra.lock(self._ra, path_revs, comment, steal_lock, lock_cb)
        return SvnLock(self, tokens)

    @convert_svn_error
    @needs_busy
    def get_log(self, path, from_revnum, to_revnum, limit, 
                discover_changed_paths, strict_node_history, revprops, rcvr, 
                pool=None):
        self.mutter('svn log %r:%r %r' % (from_revnum, to_revnum, path))
        if hasattr(svn.ra, 'get_log2'):
            return svn.ra.get_log2(self._ra, [path], 
                           from_revnum, to_revnum, limit, 
                           discover_changed_paths, strict_node_history, False, 
                           revprops, rcvr, pool)

        class LogEntry(object):
            def __init__(self, changed_paths, rev, author, date, message):
                self.changed_paths = changed_paths
                self.revprops = {}
                if svn.core.SVN_PROP_REVISION_AUTHOR in revprops:
                    self.revprops[svn.core.SVN_PROP_REVISION_AUTHOR] = author
                if svn.core.SVN_PROP_REVISION_LOG in revprops:
                    self.revprops[svn.core.SVN_PROP_REVISION_LOG] = message
                if svn.core.SVN_PROP_REVISION_DATE in revprops:
                    self.revprops[svn.core.SVN_PROP_REVISION_DATE] = date
                # FIXME: Check other revprops
                # FIXME: Handle revprops is None
                self.revision = rev
                self.has_children = None

        def rcvr_convert(orig_paths, rev, author, date, message, pool):
            rcvr(LogEntry(orig_paths, rev, author, date, message), pool)

        return svn.ra.get_log(self._ra, [path], 
                              from_revnum, to_revnum, limit, discover_changed_paths, 
                              strict_node_history, rcvr_convert, pool)

    @convert_svn_error
    @needs_busy
    def reparent(self, url):
        if hasattr(svn.ra, 'reparent'):
            self.mutter('svn reparent %r' % url)
            svn.ra.reparent(self._ra, url)
            self.url = url
        else:
            raise NotImplementedError(self.reparent)


class ConnectionPool:
    """Collection of connections to a Subversion repository."""
    def __init__(self):
        self.connections = set()

    def get(self, url):
        # Check if there is an existing connection we can use
        for c in self.connections:
            if c.url == url:
                self.connections.remove(c)
                return c
        # Nothing available? Just pick an existing one and reparent:
        if len(self.connections) == 0:
            return Connection(url)
        c = self.connections.pop()
        try:
            c.reparent(url)
            return c
        except NotImplementedError:
            self.connections.add(c)
            return Connection(url)
        except:
            self.connections.add(c)
            raise

    def add(self, connection):
        self.connections.add(connection)
    

class SvnRaTransport(Transport):
    """Fake transport for Subversion-related namespaces.
    
    This implements just as much of Transport as is necessary 
    to fool Bazaar. """
    @convert_svn_error
    def __init__(self, url="", _backing_url=None, pool=None):
        self.pool = Pool()
        bzr_url = url
        self.svn_url = bzr_to_svn_url(url)
        # _backing_url is an evil hack so the root directory of a repository 
        # can be accessed on some HTTP repositories. 
        if _backing_url is None:
            _backing_url = self.svn_url
        self._backing_url = _backing_url.rstrip("/")
        Transport.__init__(self, bzr_url)

        if pool is None:
            self.connections = ConnectionPool()
        else:
            self.connections = pool

        # Make sure that the URL is valid by connecting to it.
        self.connections.add(self.connections.get(self._backing_url))

        from bzrlib.plugins.svn import lazy_check_versions
        lazy_check_versions()

    def get_connection(self):
        return self.connections.get(self._backing_url)

    def add_connection(self, conn):
        self.connections.add(conn)

    def has(self, relpath):
        """See Transport.has()."""
        # TODO: Raise TransportNotPossible here instead and 
        # catch it in bzrdir.py
        return False

    def get(self, relpath):
        """See Transport.get()."""
        # TODO: Raise TransportNotPossible here instead and 
        # catch it in bzrdir.py
        raise NoSuchFile(path=relpath)

    def stat(self, relpath):
        """See Transport.stat()."""
        raise TransportNotPossible('stat not supported on Subversion')

    def get_uuid(self):
        conn = self.get_connection()
        try:
            return conn.get_uuid()
        finally:
            self.add_connection(conn)

    def get_repos_root(self):
        root = self.get_svn_repos_root()
        if (self.base.startswith("svn+http:") or 
            self.base.startswith("svn+https:")):
            return "svn+%s" % root
        return root

    def get_svn_repos_root(self):
        conn = self.get_connection()
        try:
            return conn.get_repos_root()
        finally:
            self.add_connection(conn)

    def get_latest_revnum(self):
        conn = self.get_connection()
        try:
            return conn.get_latest_revnum()
        finally:
            self.add_connection(conn)

    def do_switch(self, switch_rev, recurse, switch_url, editor, pool=None):
        conn = self._open_real_transport()
        try:
            return conn.do_switch(switch_rev, recurse, switch_url, editor, pool)
        finally:
            self.add_connection(conn)

    def iter_log(self, path, from_revnum, to_revnum, limit, discover_changed_paths, 
                 strict_node_history, revprops):

        assert isinstance(path, str)
        assert isinstance(from_revnum, int) and isinstance(to_revnum, int)
        assert isinstance(limit, int)
        from threading import Thread, Semaphore

        class logfetcher(Thread):
            def __init__(self, get_log):
                Thread.__init__(self)
                self.setDaemon(True)
                self.get_log = get_log
                self.pending = []
                self.semaphore = Semaphore(0)

            def next(self):
                self.semaphore.acquire()
                ret = self.pending.pop(0)
                if isinstance(ret, Exception):
                    raise ret
                return ret

            def run(self):
                def rcvr(log_entry, pool):
                    self.pending.append((log_entry.changed_paths, log_entry.revision, log_entry.revprops))
                    self.semaphore.release()
                try:
                    self.get_log(rcvr)
                    self.pending.append(None)
                except Exception, e:
                    self.pending.append(e)
                self.semaphore.release()
        
        fetcher = logfetcher(lambda rcvr: self.get_log(path, from_revnum, to_revnum, limit, discover_changed_paths, strict_node_history, revprops, rcvr))
        fetcher.start()
        return iter(fetcher.next, None)

    def get_log(self, path, from_revnum, to_revnum, limit, discover_changed_paths, 
                strict_node_history, revprops, rcvr, pool=None):
        conn = self.get_connection()
        try:
            return conn.get_log(self._request_path(path), 
                    from_revnum, to_revnum,
                    limit, discover_changed_paths, strict_node_history, 
                    revprops, rcvr, pool)
        finally:
            self.add_connection(conn)

    def _open_real_transport(self):
        if self._backing_url != self.svn_url:
            return self.connections.get(self.svn_url)
        return self.get_connection()

    def change_rev_prop(self, revnum, name, value, pool=None):
        conn = self.get_connection()
        try:
            return conn.change_rev_prop(revnum, name, value, pool)
        finally:
            self.add_connection(conn)

    def get_dir(self, path, revnum, pool=None, kind=False):
        path = self._request_path(path)
        conn = self.get_connection()
        try:
            return conn.get_dir(path, revnum, pool, kind)
        finally:
            self.add_connection(conn)

    def _request_path(self, relpath):
        if self._backing_url == self.svn_url:
            return relpath.strip("/")
        newrelpath = urlutils.join(
                urlutils.relative_url(self._backing_url+"/", self.svn_url+"/"),
                relpath).strip("/")
        self.mutter('request path %r -> %r' % (relpath, newrelpath))
        return newrelpath

    def list_dir(self, relpath):
        assert len(relpath) == 0 or relpath[0] != "/"
        if relpath == ".":
            relpath = ""
        try:
            (dirents, _, _) = self.get_dir(relpath, self.get_latest_revnum())
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_FS_NOT_DIRECTORY:
                raise NoSuchFile(relpath)
            raise
        return dirents.keys()

    def check_path(self, path, revnum):
        path = self._request_path(path)
        conn = self.get_connection()
        try:
            return conn.check_path(path, revnum)
        finally:
            self.add_connection(conn)

    def mkdir(self, relpath, mode=None):
        conn = self.get_connection()
        try:
            return conn.mkdir(relpath, mode)
        finally:
            self.add_connection(conn)

    def replay(self, revision, low_water_mark, send_deltas, editor, pool=None):
        conn = self._open_real_transport()
        try:
            return conn.replay(revision, low_water_mark, 
                                             send_deltas, editor, pool)
        finally:
            self.add_connection(conn)

    def do_update(self, revnum, recurse, editor, pool=None):
        conn = self._open_real_transport()
        try:
            return conn.do_update(revnum, recurse, editor, pool)
        finally:
            self.add_connection(conn)

    def has_capability(self, cap):
        conn = self.get_connection()
        try:
            return conn.has_capability(cap)
        finally:
            self.add_connection(conn)

    def revprop_list(self, revnum, pool=None):
        conn = self.get_connection()
        try:
            return conn.revprop_list(revnum, pool)
        finally:
            self.add_connection(conn)

    def get_commit_editor(self, revprops, done_cb, lock_token, keep_locks):
        conn = self._open_real_transport()
        try:
            return conn.get_commit_editor(revprops, done_cb,
                                         lock_token, keep_locks)
        finally:
            self.add_connection(conn)

    def listable(self):
        """See Transport.listable().
        """
        return True

    # There is no real way to do locking directly on the transport 
    # nor is there a need to as the remote server will take care of 
    # locking
    class PhonyLock(object):
        def unlock(self):
            pass

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return self.PhonyLock()

    def lock_write(self, path_revs, comment=None, steal_lock=False):
        return self.PhonyLock() # FIXME

    def _is_http_transport(self):
        return (self.svn_url.startswith("http://") or 
                self.svn_url.startswith("https://"))

    def clone_root(self):
        if self._is_http_transport():
            return SvnRaTransport(self.get_repos_root(), 
                                  bzr_to_svn_url(self.base),
                                  pool=self.connections)
        return SvnRaTransport(self.get_repos_root(),
                              pool=self.connections)

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            return SvnRaTransport(self.base, pool=self.connections)

        return SvnRaTransport(urlutils.join(self.base, offset), pool=self.connections)

    def local_abspath(self, relpath):
        """See Transport.local_abspath()."""
        absurl = self.abspath(relpath)
        if self.base.startswith("file:///"):
            return urlutils.local_path_from_url(absurl)
        raise NotLocalUrl(absurl)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return urlutils.join(self.base, relpath)
