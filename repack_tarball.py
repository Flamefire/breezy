#    repack_tarball.py -- Repack files/dirs in to tarballs.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
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

import gzip
import os
from StringIO import StringIO
import tarfile
import bz2
try:
    import hashlib
    def new_sha(*args):
        return hashlib.sha1(*args)
except ImportError:
    import sha
    def new_sha(*args):
        return sha.new(*args)
import shutil
import time
import zipfile

from bzrlib.errors import (
                           FileExists,
                           )
from bzrlib.transport import get_transport

from bzrlib.plugins.builddeb.errors import UnsupportedRepackFormat
from bzrlib.plugins.builddeb.util import open_file, open_file_via_transport


class TgzRepacker(object):
    """Repacks something to be a .tar.gz"""

    def __init__(self, source_f):
        """Create a repacker that repacks what is in source_f.

        :param source_f: a file object to read the source from.
        """
        self.source_f = source_f

    def repack(self, target_f):
        """Repacks and writes the repacked tar.gz to target_f.

        target_f should be closed after calling this method.

        :param target_f: a file object to write the result to.
        """
        raise NotImplementedError(self.repack)


class TgzTgzRepacker(TgzRepacker):
    """A TgzRepacker that just copies."""

    def repack(self, target_f):
        shutil.copyfileobj(self.source_f, target_f)


class TarTgzRepacker(TgzRepacker):
    """A TgzRepacker that just gzips the input."""

    def repack(self, target_f):
        gz = gzip.GzipFile(mode='w', fileobj=target_f)
        try:
            shutil.copyfileobj(self.source_f, gz)
        finally:
            gz.close()


class Tbz2TgzRepacker(TgzRepacker):
    """A TgzRepacker that repacks from a .tar.bz2."""

    def repack(self, target_f):
        content = bz2.decompress(self.source_f.read())
        gz = gzip.GzipFile(mode='w', fileobj=target_f)
        try:
            gz.write(content)
        finally:
            gz.close()


class ZipTgzRepacker(TgzRepacker):
    """A TgzRepacker that repacks from a .zip file."""

    def _repack_zip_to_tar(self, zip, tar):
        for info in zip.infolist():
            tarinfo = tarfile.TarInfo(info.filename)
            tarinfo.size = info.file_size
            tarinfo.mtime = time.mktime(info.date_time + (0, 1, -1))
            if info.filename.endswith("/"):
                tarinfo.mode = 0755
                tarinfo.type = tarfile.DIRTYPE
            else:
                tarinfo.mode = 0644
                tarinfo.type = tarfile.REGTYPE
            contents = StringIO(zip.read(info.filename))
            tar.addfile(tarinfo, contents)

    def repack(self, target_f):
        zip = zipfile.ZipFile(self.source_f, "r")
        try:
            tar = tarfile.open(mode="w:gz", fileobj=target_f)
            try:
                self._repack_zip_to_tar(zip, tar)
            finally:
                tar.close()
        finally:
            zip.close()


def get_filetype(filename):
    types = [".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar", ".zip"]
    for filetype in types:
        if filename.endswith(filetype):
            return filetype


def get_repacker_class(source_filename, force_gz=True):
    """Return the appropriate repacker based on the file extension."""
    filetype = get_filetype(source_filename)
    if (filetype == ".tar.gz" or filetype == ".tgz"):
        return TgzTgzRepacker
    if (filetype == ".tar.bz2" or filetype == ".tbz2"):
        if force_gz:
            return Tbz2TgzRepacker
        return TgzTgzRepacker
    if filetype == ".tar":
        return TarTgzRepacker
    if filetype == ".zip":
        return ZipTgzRepacker
    return None


def _error_if_exists(target_transport, new_name, source_name, force_gz=True):
    source_filetype = get_filetype(source_name)
    if force_gz and source_filetype != ".tar.gz":
        raise FileExists(new_name)
    source_f = open_file(source_name)
    try:
        source_sha = new_sha(source_f.read()).hexdigest()
    finally:
        source_f.close()
    target_f = open_file_via_transport(new_name, target_transport)
    try:
        target_sha = new_sha(target_f.read()).hexdigest()
    finally:
        target_f.close()
    if source_sha != target_sha:
        raise FileExists(new_name)


def _repack_directory(target_transport, new_name, source_name):
    target_transport.ensure_base()
    target_f = target_transport.open_write_stream(new_name)
    try:
        tar = tarfile.open(mode='w:gz', fileobj=target_f)
        try:
            tar.add(source_name, os.path.basename(source_name))
        finally:
            tar.close()
    finally:
        target_f.close()


def _repack_other(target_transport, new_name, source_name, force_gz=True):
    repacker_cls = get_repacker_class(source_name, force_gz=force_gz)
    if repacker_cls is None:
        raise UnsupportedRepackFormat(source_name)
    target_transport.ensure_base()
    target_f = target_transport.open_write_stream(new_name)
    try:
        source_f = open_file(source_name)
        try:
            repacker = repacker_cls(source_f)
            repacker.repack(target_f)
        finally:
            source_f.close()
    finally:
        target_f.close()


def repack_tarball(source_name, new_name, target_dir=None, force_gz=True):
    """Repack the file/dir named to a .tar.gz with the chosen name.

    This function takes a named file of either .tar.gz, .tar .tgz .tar.bz2 
    or .zip type, or a directory, and creates the file named in the second
    argument in .tar.gz format.

    If target_dir is specified then that directory will be created if it
    doesn't exist, and the new_name will be interpreted relative to that
    directory.

    The source must exist, and the target cannot exist, unless it is identical
    to the source.

    :param source_name: the current name of the file/dir
    :type source_name: string
    :param new_name: the desired name of the tarball
    :type new_name: string
    :keyword target_dir: the directory to consider new_name relative to, and
                         will be created if non-existant.
    :type target_dir: string
    :param force_gz: whether to repack other .tar files to .tar.gz.
    :return: None
    :throws NoSuchFile: if source_name doesn't exist.
    :throws FileExists: if the target filename (after considering target_dir)
                        exists, and is not identical to the source.
    :throws BzrCommandError: if the source isn't supported for repacking.
    """
    if target_dir is None:
        target_dir = "."
    if isinstance(source_name, unicode):
        source_name = source_name.encode('utf-8')
    if isinstance(new_name, unicode):
        new_name = new_name.encode('utf-8')
    if isinstance(target_dir, unicode):
        target_dir = target_dir.encode('utf-8')
    extra, new_name = os.path.split(new_name)
    target_transport = get_transport(os.path.join(target_dir, extra))
    if target_transport.has(new_name):
        _error_if_exists(target_transport, new_name, source_name,
                force_gz=force_gz)
        return
    if os.path.isdir(source_name):
        _repack_directory(target_transport, new_name, source_name)
    else:
        _repack_other(target_transport, new_name, source_name,
                force_gz=force_gz)
