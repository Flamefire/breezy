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
import tarfile
import bz2
import sha

from bzrlib.errors import (
                           FileExists,
                           BzrCommandError,
                           NotADirectory,
                           )
from bzrlib.transport import get_transport
from bzrlib import urlutils


def repack_tarball(orig_name, new_name, target_dir=None):
  """Repack the file/dir named to a .tar.gz with the chosen name.

  This function takes a named file of either .tar.gz, .tar .tgz .tar.bz2 
  or .zip type, or a directory, and creates the file named in the second
  argument in .tar.gz format.

  If target_dir is specified then that directory will be created if it
  doesn't exist, and the new_name will be interpreted relative to that
  directory.
  
  The source must exist, and the target cannot exist.

  :param orig_name: the curent name of the file/dir
  :type orig_name: string
  :param new_name: the desired name of the tarball
  :type new_name: string
  :keyword target_dir: the directory to consider new_name relative to, and
                       will be created if non-existant.
  :type target_dir: string
  :return: None
  :warning: .zip files are currently unsupported.
  :throws NoSuchFile: if orig_name doesn't exist.
  :throws NotADirectory: if target_dir exists and is not a directory.
  :throws FileExists: if the target filename (after considering target_dir)
                      exists, and is not identical to the source.
  :throes BzrCommandError: if the source isn't supported for repacking.
  """
  if target_dir is not None:
    if not os.path.exists(target_dir):
      os.mkdir(target_dir)
    else:
      if not os.path.isdir(target_dir):
        raise NotADirectory(target_dir)
    new_name = os.path.join(target_dir, new_name)
  if os.path.exists(new_name):
    if not orig_name.endswith('.tar.gz'):
      raise FileExists(new_name)
    f = open(orig_name)
    try:
      orig_sha = sha.sha(f.read()).hexdigest()
    finally:
      f.close()
    f = open(new_name)
    try:
      new_sha = sha.sha(f.read()).hexdigest()
    finally:
      f.close()
    if orig_sha != new_sha:
      raise FileExists(new_name)
    return
  if os.path.isdir(orig_name):
    tar = tarfile.open(new_name, 'w:gz')
    try:
      tar.add(orig_name, os.path.basename(orig_name))
    finally:
      tar.close()
  else:
    if isinstance(orig_name, unicode):
      orig_name = orig_name.encode('utf-8')
    if isinstance(new_name, unicode):
      new_name = new_name.encode('utf-8')
    base_dir, path = urlutils.split(orig_name)
    transport = get_transport(base_dir)
    trans_file = transport.get(path)
    try:
      if orig_name.endswith('.tar.gz') or orig_name.endswith('.tgz'):
        dest = open(new_name, 'wb')
        try:
          dest.write(trans_file.read())
        finally:
          dest.close()
      elif orig_name.endswith('.tar'):
        gz = gzip.GzipFile(new_name, 'w')
        try:
          gz.write(trans_file.read())
        finally:
          gz.close()
      elif orig_name.endswith('.tar.bz2'):
        old_tar_content = trans_file.read()
        old_tar_content_decompressed = bz2.decompress(old_tar_content)
        gz = gzip.GzipFile(new_name, 'w')
        try:
          gz.write(old_tar_content_decompressed)
        finally:
          gz.close()
      elif orig_name.endswith('.zip') or zipfile.is_zipfile(orig_name):
        # TarFileCompat may be easier, but it's buggy (Python issue 3039).
        # method/code has been adopted from the patch there.
        import zipfile
        import calendar
        try:
            from cStringIO import StringIO
        except ImportError:
            from StringIO import StringIO
        zip = zipfile.ZipFile(orig_name, 'r')
        tgz = tarfile.open(new_name, "w|gz")
        for zinfo in zip.infolist():
          bytes = zip.read(zinfo.filename)
          tinfo = tarfile.TarInfo(zinfo.filename)
          tinfo.size = len(bytes)
          tinfo.mtime = calendar.timegm(zinfo.date_time)
          tgz.addfile(tinfo, StringIO(bytes))
        tgz.close()

      else:
        raise BzrCommandError('Unsupported format for repack: %s' % orig_name)
    finally:
      trans_file.close()

# vim: ts=2 sts=2 sw=2

