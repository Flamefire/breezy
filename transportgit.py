# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""A Git repository implementation that uses a Bazaar transport."""

from cStringIO import StringIO

import os
import urllib

from dulwich.errors import (
    NotGitRepository,
    NoIndexPresent,
    )
from dulwich.objects import (
    ShaFile,
    )
from dulwich.object_store import (
    PackBasedObjectStore,
    PACKDIR,
    )
from dulwich.pack import (
    MemoryPackIndex,
    PackData,
    Pack,
    iter_sha1,
    load_pack_index_file,
    write_pack_data,
    write_pack_index_v2,
    )
from dulwich.repo import (
    BaseRepo,
    RefsContainer,
    BASE_DIRECTORIES,
    INDEX_FILENAME,
    OBJECTDIR,
    REFSDIR,
    SYMREF,
    check_ref_format,
    read_packed_refs_with_peeled,
    read_packed_refs,
    write_packed_refs,
    )

from bzrlib import (
    transport as _mod_transport,
    )
from bzrlib.errors import (
    FileExists,
    NoSuchFile,
    TransportNotPossible,
    )


class TransportRefsContainer(RefsContainer):
    """Refs container that reads refs from a transport."""

    def __init__(self, transport):
        self.transport = transport
        self._packed_refs = None
        self._peeled_refs = None

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.transport)

    def _ensure_dir_exists(self, path):
        for n in range(path.count("/")):
            dirname = "/".join(path.split("/")[:n+1])
            try:
                self.transport.mkdir(dirname)
            except FileExists:
                pass

    def subkeys(self, base):
        keys = set()
        try:
            iter_files = self.transport.clone(base).iter_files_recursive()
            keys.update(("%s/%s" % (base, urllib.unquote(refname))).strip("/") for 
                    refname in iter_files if check_ref_format("%s/%s" % (base, refname)))
        except (TransportNotPossible, NoSuchFile):
            pass
        for key in self.get_packed_refs():
            if key.startswith(base):
                keys.add(key[len(base):].strip("/"))
        return keys

    def allkeys(self):
        keys = set()
        try:
            self.transport.get_bytes("HEAD")
        except NoSuchFile:
            pass
        else:
            keys.add("HEAD")
        try:
            iter_files = list(self.transport.clone("refs").iter_files_recursive())
            for filename in iter_files:
                refname = "refs/%s" % urllib.unquote(filename)
                if check_ref_format(refname):
                    keys.add(refname)
        except (TransportNotPossible, NoSuchFile):
            pass
        keys.update(self.get_packed_refs())
        return keys

    def get_packed_refs(self):
        """Get contents of the packed-refs file.

        :return: Dictionary mapping ref names to SHA1s

        :note: Will return an empty dictionary when no packed-refs file is
            present.
        """
        # TODO: invalidate the cache on repacking
        if self._packed_refs is None:
            # set both to empty because we want _peeled_refs to be
            # None if and only if _packed_refs is also None.
            self._packed_refs = {}
            self._peeled_refs = {}
            try:
                f = self.transport.get("packed-refs")
            except NoSuchFile:
                return {}
            try:
                first_line = iter(f).next().rstrip()
                if (first_line.startswith("# pack-refs") and " peeled" in
                        first_line):
                    for sha, name, peeled in read_packed_refs_with_peeled(f):
                        self._packed_refs[name] = sha
                        if peeled:
                            self._peeled_refs[name] = peeled
                else:
                    f.seek(0)
                    for sha, name in read_packed_refs(f):
                        self._packed_refs[name] = sha
            finally:
                f.close()
        return self._packed_refs

    def get_peeled(self, name):
        """Return the cached peeled value of a ref, if available.

        :param name: Name of the ref to peel
        :return: The peeled value of the ref. If the ref is known not point to a
            tag, this will be the SHA the ref refers to. If the ref may point to
            a tag, but no cached information is available, None is returned.
        """
        self.get_packed_refs()
        if self._peeled_refs is None or name not in self._packed_refs:
            # No cache: no peeled refs were read, or this ref is loose
            return None
        if name in self._peeled_refs:
            return self._peeled_refs[name]
        else:
            # Known not peelable
            return self[name]

    def read_loose_ref(self, name):
        """Read a reference file and return its contents.

        If the reference file a symbolic reference, only read the first line of
        the file. Otherwise, only read the first 40 bytes.

        :param name: the refname to read, relative to refpath
        :return: The contents of the ref file, or None if the file does not
            exist.
        :raises IOError: if any other error occurs
        """
        try:
            f = self.transport.get(name)
        except NoSuchFile:
            return None
        f = StringIO(f.read())
        try:
            header = f.read(len(SYMREF))
            if header == SYMREF:
                # Read only the first line
                return header + iter(f).next().rstrip("\r\n")
            else:
                # Read only the first 40 bytes
                return header + f.read(40-len(SYMREF))
        finally:
            f.close()

    def _remove_packed_ref(self, name):
        if self._packed_refs is None:
            return
        # reread cached refs from disk, while holding the lock

        self._packed_refs = None
        self.get_packed_refs()

        if name not in self._packed_refs:
            return

        del self._packed_refs[name]
        if name in self._peeled_refs:
            del self._peeled_refs[name]
        f = self.transport.open_write_stream("packed-refs")
        try:
            write_packed_refs(f, self._packed_refs, self._peeled_refs)
        finally:
            f.close()

    def set_symbolic_ref(self, name, other):
        """Make a ref point at another ref.

        :param name: Name of the ref to set
        :param other: Name of the ref to point at
        """
        self._check_refname(name)
        self._check_refname(other)
        self._ensure_dir_exists(name)
        self.transport.put_bytes(name, SYMREF + other + '\n')

    def set_if_equals(self, name, old_ref, new_ref):
        """Set a refname to new_ref only if it currently equals old_ref.

        This method follows all symbolic references, and can be used to perform
        an atomic compare-and-swap operation.

        :param name: The refname to set.
        :param old_ref: The old sha the refname must refer to, or None to set
            unconditionally.
        :param new_ref: The new sha the refname will refer to.
        :return: True if the set was successful, False otherwise.
        """
        try:
            realname, _ = self._follow(name)
        except KeyError:
            realname = name
        self._ensure_dir_exists(realname)
        self.transport.put_bytes(realname, new_ref+"\n")
        return True

    def add_if_new(self, name, ref):
        """Add a new reference only if it does not already exist.

        This method follows symrefs, and only ensures that the last ref in the
        chain does not exist.

        :param name: The refname to set.
        :param ref: The new sha the refname will refer to.
        :return: True if the add was successful, False otherwise.
        """
        try:
            realname, contents = self._follow(name)
            if contents is not None:
                return False
        except KeyError:
            realname = name
        self._check_refname(realname)
        self._ensure_dir_exists(realname)
        self.transport.put_bytes(realname, ref+"\n")
        return True

    def remove_if_equals(self, name, old_ref):
        """Remove a refname only if it currently equals old_ref.

        This method does not follow symbolic references. It can be used to
        perform an atomic compare-and-delete operation.

        :param name: The refname to delete.
        :param old_ref: The old sha the refname must refer to, or None to delete
            unconditionally.
        :return: True if the delete was successful, False otherwise.
        """
        self._check_refname(name)
        # may only be packed
        try:
            self.transport.delete(name)
        except NoSuchFile:
            pass
        self._remove_packed_ref(name)
        return True

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default


class TransportRepo(BaseRepo):

    def __init__(self, transport, bare, refs_text=None):
        self.transport = transport
        self.bare = bare
        if self.bare:
            self._controltransport = self.transport
        else:
            self._controltransport = self.transport.clone('.git')
        object_store = TransportObjectStore(
            self._controltransport.clone(OBJECTDIR))
        if refs_text is not None:
            from dulwich.repo import InfoRefsContainer # dulwich >= 0.8.2
            refs_container = InfoRefsContainer(StringIO(refs_text))
            try:
                head = TransportRefsContainer(self._controltransport).read_loose_ref("HEAD")
            except KeyError:
                pass
            else:
                refs_container._refs["HEAD"] = head
        else:
            refs_container = TransportRefsContainer(self._controltransport)
        super(TransportRepo, self).__init__(object_store, 
                refs_container)

    def get_named_file(self, path):
        """Get a file from the control dir with a specific name.

        Although the filename should be interpreted as a filename relative to
        the control dir in a disk-baked Repo, the object returned need not be
        pointing to a file in that location.

        :param path: The path to the file, relative to the control dir.
        :return: An open file object, or None if the file does not exist.
        """
        try:
            return self._controltransport.get(path.lstrip('/'))
        except NoSuchFile:
            return None

    def _put_named_file(self, relpath, contents):
        self._controltransport.put_bytes(relpath, contents)

    def index_path(self):
        """Return the path to the index file."""
        return self._controltransport.local_abspath(INDEX_FILENAME)

    def open_index(self):
        """Open the index for this repository."""
        from dulwich.index import Index
        if not self.has_index():
            raise NoIndexPresent()
        return Index(self.index_path())

    def has_index(self):
        """Check if an index is present."""
        # Bare repos must never have index files; non-bare repos may have a
        # missing index file, which is treated as empty.
        return not self.bare

    def get_config(self):
        from dulwich.config import ConfigFile
        try:
            return ConfigFile.from_file(self._controltransport.get('config'))
        except NoSuchFile:
            return ConfigFile()

    def get_config_stack(self):
        from dulwich.config import StackedConfig
        backends = []
        p = self.get_config()
        if p is not None:
            backends.append(p)
            writable = p
        else:
            writable = None
        backends.extend(StackedConfig.default_backends())
        return StackedConfig(backends, writable=writable)

    def __repr__(self):
        return "<%s for %r>" % (self.__class__.__name__, self.transport)

    @classmethod
    def init(cls, transport, bare=False):
        if not bare:
            transport.mkdir(".git")
            control_transport = transport.clone(".git")
        else:
            control_transport = transport
        for d in BASE_DIRECTORIES:
            control_transport.mkdir("/".join(d))
        control_transport.mkdir(OBJECTDIR)
        TransportObjectStore.init(control_transport.clone(OBJECTDIR))
        ret = cls(transport, bare)
        ret.refs.set_symbolic_ref("HEAD", "refs/heads/master")
        ret._init_files(bare)
        return ret


class TransportObjectStore(PackBasedObjectStore):
    """Git-style object store that exists on disk."""

    def __init__(self, transport):
        """Open an object store.

        :param transport: Transport to open data from
        """
        super(TransportObjectStore, self).__init__()
        self.transport = transport
        self.pack_transport = self.transport.clone(PACKDIR)
        self._alternates = None

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.transport)

    def _pack_cache_stale(self):
        return False # FIXME

    @property
    def alternates(self):
        if self._alternates is not None:
            return self._alternates
        self._alternates = []
        for path in self._read_alternate_paths():
            # FIXME: Check path
            t = _mod_transport.get_transport_from_path(path)
            self._alternates.append(self.__class__(t))
        return self._alternates

    def _read_alternate_paths(self):
        try:
            f = self.transport.get("info/alternates")
        except NoSuchFile:
            return []
        ret = []
        try:
            for l in f.read().splitlines():
                if l[0] == "#":
                    continue
                if os.path.isabs(l):
                    continue
                ret.append(l)
            return ret
        finally:
            f.close()

    def _pack_names(self):
        try:
            f = self.transport.get('info/packs')
        except NoSuchFile:
            return self.pack_transport.list_dir(".")
        else:
            ret = []
            for line in f.read().splitlines():
                if not line:
                    continue
                (kind, name) = line.split(" ", 1)
                if kind != "P":
                    continue
                ret.append(name)
            return ret

    def _load_packs(self):
        ret = []
        for name in self._pack_names():
            if name.startswith("pack-") and name.endswith(".pack"):
                try:
                    size = self.pack_transport.stat(name).st_size
                except TransportNotPossible:
                    # FIXME: This reads the whole pack file at once
                    f = self.pack_transport.get(name)
                    contents = f.read()
                    pd = PackData(name, StringIO(contents), size=len(contents))
                else:
                    pd = PackData(name, self.pack_transport.get(name),
                            size=size)
                idxname = name.replace(".pack", ".idx")
                idx = load_pack_index_file(idxname, self.pack_transport.get(idxname))
                pack = Pack.from_objects(pd, idx)
                ret.append(pack)
        return ret

    def _iter_loose_objects(self):
        for base in self.transport.list_dir('.'):
            if len(base) != 2:
                continue
            for rest in self.transport.list_dir(base):
                yield base+rest

    def _split_loose_object(self, sha):
        return (sha[:2], sha[2:])

    def _remove_loose_object(self, sha):
        path = '%s/%s' % self._split_loose_object(sha)
        self.transport.delete(path)

    def _get_loose_object(self, sha):
        path = '%s/%s' % self._split_loose_object(sha)
        try:
            return ShaFile.from_file(self.transport.get(path))
        except NoSuchFile:
            return None

    def add_object(self, obj):
        """Add a single object to this object store.

        :param obj: Object to add
        """
        (dir, file) = self._split_loose_object(obj.id)
        try:
            self.transport.mkdir(dir)
        except FileExists:
            pass
        path = "%s/%s" % (dir, file)
        if self.transport.has(path):
            return # Already there, no need to write again
        self.transport.put_bytes(path, obj.as_legacy_object())

    def move_in_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        p = PackData(None, f, len(f.getvalue()))
        entries = p.sorted_entries()
        basename = "pack-%s" % iter_sha1(entry[0] for entry in entries)
        f.seek(0)
        self.pack_transport.put_file(basename + ".pack", f)
        idxfile = self.pack_transport.open_write_stream(basename + ".idx")
        try:
            write_pack_index_v2(idxfile, entries, p.get_stored_checksum())
        finally:
            idxfile.close()
        idxfile = self.pack_transport.get(basename + ".idx")
        idx = load_pack_index_file(basename+".idx", idxfile)
        final_pack = Pack.from_objects(p, idx)
        self._add_known_pack(final_pack)
        return final_pack

    def add_thin_pack(self):
        """Add a new thin pack to this object store.

        Thin packs are packs that contain deltas with parents that exist
        in a different pack.
        """
        from cStringIO import StringIO
        f = StringIO()
        def commit():
            if len(f.getvalue()) > 0:
                return self.move_in_thin_pack(f)
            else:
                return None
        return f, commit

    def move_in_thin_pack(self, f):
        """Move a specific file containing a pack into the pack directory.

        :note: The file should be on the same file system as the
            packs directory.

        :param path: Path to the pack file.
        """
        f.seek(0)
        data = PackData.from_file(self.get_raw, f, len(f.getvalue()))
        idx = MemoryPackIndex(data.sorted_entries(), data.get_stored_checksum())
        p = Pack.from_objects(data, idx)

        pack_sha = idx.objects_sha1()

        datafile = self.pack_transport.open_write_stream(
                "pack-%s.pack" % pack_sha)
        try:
            entries, data_sum = write_pack_data(datafile, p.pack_tuples())
        finally:
            datafile.close()
        entries.sort()
        idxfile = self.pack_transport.open_write_stream(
            "pack-%s.idx" % pack_sha)
        try:
            write_pack_index_v2(idxfile, data.sorted_entries(), data_sum)
        finally:
            idxfile.close()
        final_pack = Pack("pack-%s" % pack_sha)
        self._add_known_pack(final_pack)
        return final_pack

    def add_pack(self):
        """Add a new pack to this object store. 

        :return: Fileobject to write to and a commit function to 
            call when the pack is finished.
        """
        from cStringIO import StringIO
        f = StringIO()
        def commit():
            if len(f.getvalue()) > 0:
                return self.move_in_pack(f)
            else:
                return None
        return f, commit

    @classmethod
    def init(cls, transport):
        transport.mkdir('info')
        transport.mkdir(PACKDIR)
        return cls(transport)
