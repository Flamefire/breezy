#    quilt.py -- Quilt patch handling
#    Copyright (C) 2011 Canonical Ltd.
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

"""Quilt patch handling."""

from __future__ import absolute_import

import errno
import os
import signal
import subprocess
from bzrlib import (
    errors,
    trace,
    )


class QuiltError(errors.BzrError):

    _fmt = "An error (%(retcode)d) occurred running quilt: %(stderr)s%(extra)s"

    def __init__(self, retcode, stdout, stderr):
        self.retcode = retcode
        self.stderr = stderr
        if stdout is not None:
            self.extra = "\n\n%s" % stdout
        else:
            self.extra = ""
        self.stdout = stdout


def run_quilt(args, working_dir, series_file=None, patches_dir=None, quiet=None):
    """Run quilt.

    :param args: Arguments to quilt
    :param working_dir: Working dir
    :param series_file: Optional path to the series file
    :param patches_dir: Optional path to the patches
    :param quilt: Whether to be quiet (quilt stderr not to terminal)
    :raise QuiltError: When running quilt fails
    """
    def subprocess_setup():
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    env = {}
    if patches_dir is not None:
        env["QUILT_PATCHES"] = patches_dir
    else:
        env["QUILT_PATCHES"] = os.path.join(working_dir, "debian", "patches")
    if series_file is not None:
        env["QUILT_SERIES"] = series_file
    else:
        env["QUILT_SERIES"] = os.path.join(env["QUILT_PATCHES"], "series")
    # Hide output if -q is in use.
    if quiet is None:
        quiet = trace.is_quiet()
    if quiet:
        stderr =  subprocess.STDOUT
    else:
        stderr = subprocess.PIPE
    command = ["quilt"] + args
    trace.mutter("running: %r", command)
    if not os.path.isdir(working_dir):
        raise AssertionError("%s is not a valid directory" % working_dir)
    try:
        proc = subprocess.Popen(command, cwd=working_dir, env=env,
                stdin=subprocess.PIPE, preexec_fn=subprocess_setup,
                stdout=subprocess.PIPE, stderr=stderr)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        raise errors.BzrError("quilt is not installed, please install it")
    output = proc.communicate()
    if proc.returncode not in (0, 2):
        raise QuiltError(proc.returncode, output[0], output[1])
    if output[0] is None:
        return ""
    return output[0]


def quilt_pop_all(working_dir, patches_dir=None, series_file=None, quiet=None):
    """Pop all patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["pop", "-a"], working_dir=working_dir,
        patches_dir=patches_dir, series_file=series_file, quiet=quiet)


def quilt_pop(working_dir, patch, patches_dir=None, series_file=None, quiet=None):
    """Pop a patch.

    :param working_dir: Directory to work in
    :param patch: Patch to apply
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["pop", patch], working_dir=working_dir,
        patches_dir=patches_dir, series_file=series_file, quiet=quiet)


def quilt_push_all(working_dir, patches_dir=None, series_file=None, quiet=None):
    """Push all patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["push", "-a"], working_dir=working_dir,
            patches_dir=patches_dir, series_file=series_file, quiet=quiet)


def quilt_push(working_dir, patch, patches_dir=None, series_file=None, quiet=None):
    """Push a patch.

    :param working_dir: Directory to work in
    :param patch: Patch to push
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["push", patch], working_dir=working_dir,
            patches_dir=patches_dir, series_file=series_file, quiet=quiet)


def quilt_applied(working_dir, patches_dir=None, series_file=None):
    """Find the list of applied quilt patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    try:
        return run_quilt(["applied"], working_dir=working_dir, patches_dir=patches_dir, series_file=series_file).splitlines()
    except QuiltError, e:
        if e.retcode == 1:
            return []
        raise


def quilt_unapplied(working_dir, patches_dir=None, series_file=None):
    """Find the list of unapplied quilt patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    try:
        return run_quilt(["unapplied"], working_dir=working_dir,
                patches_dir=patches_dir, series_file=series_file).splitlines()
    except QuiltError, e:
        if e.retcode == 1:
            return []
        raise


def quilt_series(working_dir, patches_dir=None, series_file=None):
    """Find the list of patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["series"], working_dir=working_dir, patches_dir=patches_dir, series_file=series_file).splitlines()

