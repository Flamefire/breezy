# Copyright (C) 2005-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Messages and logging.

Messages are supplied by callers as a string-formatting template, plus values
to be inserted into it.  The actual %-formatting is deferred to the log
library so that it doesn't need to be done for messages that won't be emitted.

Messages are classified by severity levels: critical, error, warning, info,
and debug.

They can be sent to two places: to stderr, and to ~/.bzr.log.  For purposes
such as running the test suite, they can also be redirected away from both of
those two places to another location.

~/.bzr.log gets all messages, and full tracebacks for uncaught exceptions.
This trace file is always in UTF-8, regardless of the user's default encoding,
so that we can always rely on writing any message.

Output to stderr depends on the mode chosen by the user.  By default, messages
of info and above are sent out, which results in progress messages such as the
list of files processed by add and commit.  In debug mode, stderr gets debug messages too.

Errors that terminate an operation are generally passed back as exceptions;
others may be just emitted as messages.

Exceptions are reported in a brief form to stderr so as not to look scary.
BzrErrors are required to be able to format themselves into a properly
explanatory message.  This is not true for builtin exceptions such as
KeyError, which typically just str to "0".  They're printed in a different
form.
"""

# FIXME: Unfortunately it turns out that python's logging module
# is quite expensive, even when the message is not printed by any handlers.
# We should perhaps change back to just simply doing it here.
#
# On the other hand, as of 1.2 we generally only call the mutter() statement
# if (according to debug_flags) we actually intend to write it.  So the
# increased cost of logging.py is not so bad, and we could standardize on
# that.

import codecs
import logging
import os
import sys
import time

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from cStringIO import StringIO
import errno
import locale
import traceback
""")

import bzrlib

from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_in,
    )

lazy_import(globals(), """
from bzrlib import (
    debug,
    errors,
    osutils,
    plugin,
    symbol_versioning,
    ui,
    )
""")


# global verbosity for bzrlib; controls the log level for stderr; 0=normal; <0
# is quiet; >0 is verbose.
_verbosity_level = 0

# File-like object where mutter/debug output is currently sent.  Can be
# changed by _push_log_file etc.  This is directly manipulated by some
# external code; maybe there should be functions to do that more precisely
# than push/pop_log_file.
_trace_file = None

# Absolute path for ~/.bzr.log.  Not changed even if the log/trace output is
# redirected elsewhere.  Used to show the location in --version.
_bzr_log_filename = None

# The time the first message was written to the trace file, so that we can
# show relative times since startup.
_bzr_log_start_time = bzrlib._start_time


# held in a global for quick reference
_bzr_logger = logging.getLogger('bzr')


def note(*args, **kwargs):
    # FIXME note always emits utf-8, regardless of the terminal encoding
    #
    # FIXME: clearing the ui and then going through the abstract logging
    # framework is whack; we should probably have a logging Handler that
    # deals with terminal output if needed.
    import bzrlib.ui
    bzrlib.ui.ui_factory.clear_term()
    _bzr_logger.info(*args, **kwargs)


def warning(*args, **kwargs):
    import bzrlib.ui
    bzrlib.ui.ui_factory.clear_term()
    _bzr_logger.warning(*args, **kwargs)


@deprecated_function(deprecated_in((2, 1, 0)))
def info(*args, **kwargs):
    """Deprecated: use trace.note instead."""
    note(*args, **kwargs)


@deprecated_function(deprecated_in((2, 1, 0)))
def log_error(*args, **kwargs):
    """Deprecated: use bzrlib.trace.show_error instead"""
    _bzr_logger.error(*args, **kwargs)


@deprecated_function(deprecated_in((2, 1, 0)))
def error(*args, **kwargs):
    """Deprecated: use bzrlib.trace.show_error instead"""
    _bzr_logger.error(*args, **kwargs)


def show_error(*args, **kwargs):
    """Show an error message to the user.

    Don't use this for exceptions, use report_exception instead.
    """
    _bzr_logger.error(*args, **kwargs)


def mutter(fmt, *args):
    if _trace_file is None:
        return
    # XXX: Don't check this every time; instead anyone who closes the file
    # ought to deregister it.  We can tolerate None.
    if (getattr(_trace_file, 'closed', None) is not None) and _trace_file.closed:
        return

    if isinstance(fmt, unicode):
        fmt = fmt.encode('utf8')

    if len(args) > 0:
        # It seems that if we do ascii % (unicode, ascii) we can
        # get a unicode cannot encode ascii error, so make sure that "fmt"
        # is a unicode string
        real_args = []
        for arg in args:
            if isinstance(arg, unicode):
                arg = arg.encode('utf8')
            real_args.append(arg)
        out = fmt % tuple(real_args)
    else:
        out = fmt
    now = time.time()
    timestamp = '%0.3f  ' % (now - _bzr_log_start_time,)
    out = timestamp + out + '\n'
    _trace_file.write(out)
    # there's no explicit flushing; the file is typically line buffered.


def mutter_callsite(stacklevel, fmt, *args):
    """Perform a mutter of fmt and args, logging the call trace.

    :param stacklevel: The number of frames to show. None will show all
        frames.
    :param fmt: The format string to pass to mutter.
    :param args: A list of substitution variables.
    """
    outf = StringIO()
    if stacklevel is None:
        limit = None
    else:
        limit = stacklevel + 1
    traceback.print_stack(limit=limit, file=outf)
    formatted_lines = outf.getvalue().splitlines()
    formatted_stack = '\n'.join(formatted_lines[:-2])
    mutter(fmt + "\nCalled from:\n%s", *(args + (formatted_stack,)))


def _rollover_trace_maybe(trace_fname):
    import stat
    try:
        size = os.stat(trace_fname)[stat.ST_SIZE]
        if size <= 4 << 20:
            return
        old_fname = trace_fname + '.old'
        osutils.rename(trace_fname, old_fname)
    except OSError:
        return


def _get_bzr_log_filename():
    bzr_log = os.environ.get('BZR_LOG')
    if bzr_log:
        return bzr_log
    home = os.environ.get('BZR_HOME')
    if home is None:
        if sys.platform == 'win32':
            from bzrlib import win32utils
            home = win32utils.get_home_location()
        else:
            home = os.path.expanduser('~')
    return os.path.join(home, '.bzr.log')


def _open_bzr_log():
    """Open the .bzr.log trace file.

    If the log is more than a particular length, the old file is renamed to
    .bzr.log.old and a new file is started.  Otherwise, we append to the
    existing file.

    This sets the global _bzr_log_filename.
    """
    global _bzr_log_filename

    def create_log_file(filename):
        """Create the .bzr.log file.

        It inherits the ownership and permissions (masked by umask) from
        the containing directory to cope better with being run under sudo
        with $HOME still set to the user's homedir.
        """
        buffering = 0 # unbuffered
        flags = os.O_WRONLY | os.O_APPEND | osutils.O_TEXT
        while True:
            try:
                fd = os.open(filename, flags)
                logfile = os.fdopen(fd, 'at', buffering)
                return logfile
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise
            try:
                flags = flags | os.O_CREAT | os.O_EXCL
                permissions = 0644
                fd = os.open(filename, flags, permissions)
                logfile = os.fdopen(fd, 'at', buffering)
            except OSError, e:
                if e.errno != errno.EEXIST:
                    raise
            else:
                osutils.copy_ownership_from_path(filename)
                return logfile


    _bzr_log_filename = _get_bzr_log_filename()
    _rollover_trace_maybe(_bzr_log_filename)
    try:
        bzr_log_file = create_log_file(_bzr_log_filename)
        bzr_log_file.write('\n')
        if bzr_log_file.tell() <= 2:
            bzr_log_file.write("this is a debug log for diagnosing/reporting problems in bzr\n")
            bzr_log_file.write("you can delete or truncate this file, or include sections in\n")
            bzr_log_file.write("bug reports to https://bugs.launchpad.net/bzr/+filebug\n\n")

        return bzr_log_file

    except IOError, e:
        # If we are failing to open the log, then most likely logging has not
        # been set up yet. So we just write to stderr rather than using
        # 'warning()'. If we using warning(), users get the unhelpful 'no
        # handlers registered for "bzr"' when something goes wrong on the
        # server. (bug #503886)
        sys.stderr.write("failed to open trace file: %s\n" % (e,))
    # TODO: What should happen if we fail to open the trace file?  Maybe the
    # objects should be pointed at /dev/null or the equivalent?  Currently
    # returns None which will cause failures later.
    return None


def enable_default_logging():
    """Configure default logging: messages to stderr and debug to .bzr.log

    This should only be called once per process.

    Non-command-line programs embedding bzrlib do not need to call this.  They
    can instead either pass a file to _push_log_file, or act directly on
    logging.getLogger("bzr").

    Output can be redirected away by calling _push_log_file.
    """
    # Do this before we open the log file, so we prevent
    # get_terminal_encoding() from mutter()ing multiple times
    term_encoding = osutils.get_terminal_encoding()
    start_time = osutils.format_local_date(_bzr_log_start_time,
                                           timezone='local')
    # create encoded wrapper around stderr
    bzr_log_file = _open_bzr_log()
    if bzr_log_file is not None:
        bzr_log_file.write(start_time.encode('utf-8') + '\n')
    push_log_file(bzr_log_file,
        r'[%(process)5d] %(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
        r'%Y-%m-%d %H:%M:%S')
    # after hooking output into bzr_log, we also need to attach a stderr
    # handler, writing only at level info and with encoding
    writer_factory = codecs.getwriter(term_encoding)
    encoded_stderr = writer_factory(sys.stderr, errors='replace')
    stderr_handler = logging.StreamHandler(encoded_stderr)
    stderr_handler.setLevel(logging.INFO)
    logging.getLogger('bzr').addHandler(stderr_handler)


def push_log_file(to_file, log_format=None, date_format=None):
    """Intercept log and trace messages and send them to a file.

    :param to_file: A file-like object to which messages will be sent.

    :returns: A memento that should be passed to _pop_log_file to restore the
    previously active logging.
    """
    global _trace_file
    # make a new handler
    new_handler = logging.StreamHandler(to_file)
    new_handler.setLevel(logging.DEBUG)
    if log_format is None:
        log_format = '%(levelname)8s  %(message)s'
    new_handler.setFormatter(logging.Formatter(log_format, date_format))
    # save and remove any existing log handlers
    bzr_logger = logging.getLogger('bzr')
    old_handlers = bzr_logger.handlers[:]
    del bzr_logger.handlers[:]
    # set that as the default logger
    bzr_logger.addHandler(new_handler)
    bzr_logger.setLevel(logging.DEBUG)
    # TODO: check if any changes are needed to the root logger
    #
    # TODO: also probably need to save and restore the level on bzr_logger.
    # but maybe we can avoid setting the logger level altogether, and just set
    # the level on the handler?
    #
    # save the old trace file
    old_trace_file = _trace_file
    # send traces to the new one
    _trace_file = to_file
    result = new_handler, _trace_file
    return ('log_memento', old_handlers, new_handler, old_trace_file, to_file)


def pop_log_file((magic, old_handlers, new_handler, old_trace_file, new_trace_file)):
    """Undo changes to logging/tracing done by _push_log_file.

    This flushes, but does not close the trace file.

    Takes the memento returned from _push_log_file."""
    global _trace_file
    _trace_file = old_trace_file
    bzr_logger = logging.getLogger('bzr')
    bzr_logger.removeHandler(new_handler)
    # must be closed, otherwise logging will try to close it atexit, and the
    # file will likely already be closed underneath.
    new_handler.close()
    bzr_logger.handlers = old_handlers
    new_trace_file.flush()


def log_exception_quietly():
    """Log the last exception to the trace file only.

    Used for exceptions that occur internally and that may be
    interesting to developers but not to users.  For example,
    errors loading plugins.
    """
    mutter(traceback.format_exc())


def set_verbosity_level(level):
    """Set the verbosity level.

    :param level: -ve for quiet, 0 for normal, +ve for verbose
    """
    global _verbosity_level
    _verbosity_level = level
    _update_logging_level(level < 0)
    ui.ui_factory.be_quiet(level < 0)


def get_verbosity_level():
    """Get the verbosity level.

    See set_verbosity_level() for values.
    """
    return _verbosity_level


def be_quiet(quiet=True):
    if quiet:
        set_verbosity_level(-1)
    else:
        set_verbosity_level(0)


def _update_logging_level(quiet=True):
    """Hide INFO messages if quiet."""
    if quiet:
        _bzr_logger.setLevel(logging.WARNING)
    else:
        _bzr_logger.setLevel(logging.INFO)


def is_quiet():
    """Is the verbosity level negative?"""
    return _verbosity_level < 0


def is_verbose():
    """Is the verbosity level positive?"""
    return _verbosity_level > 0


def debug_memory(message='', short=True):
    """Write out a memory dump."""
    if sys.platform == 'win32':
        from bzrlib import win32utils
        win32utils.debug_memory_win32api(message=message, short=short)
    else:
        _debug_memory_proc(message=message, short=short)


_short_fields = ('VmPeak', 'VmSize', 'VmRSS')

def _debug_memory_proc(message='', short=True):
    try:
        status_file = file('/proc/%s/status' % os.getpid(), 'rb')
    except IOError:
        return
    try:
        status = status_file.read()
    finally:
        status_file.close()
    if message:
        note(message)
    for line in status.splitlines():
        if not short:
            note(line)
        else:
            for field in _short_fields:
                if line.startswith(field):
                    note(line)
                    break


def report_exception(exc_info, err_file):
    """Report an exception to err_file (typically stderr) and to .bzr.log.

    This will show either a full traceback or a short message as appropriate.

    :return: The appropriate exit code for this error.
    """
    # Log the full traceback to ~/.bzr.log
    log_exception_quietly()
    if 'error' in debug.debug_flags:
        print_exception(exc_info, err_file)
        return errors.EXIT_ERROR
    exc_type, exc_object, exc_tb = exc_info
    if (isinstance(exc_object, IOError)
        and getattr(exc_object, 'errno', None) == errno.EPIPE):
        err_file.write("bzr: broken pipe\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, KeyboardInterrupt):
        err_file.write("bzr: interrupted\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, MemoryError):
        err_file.write("bzr: out of memory\n")
        return errors.EXIT_ERROR
    elif isinstance(exc_object, ImportError) \
        and str(exc_object).startswith("No module named "):
        report_user_error(exc_info, err_file,
            'You may need to install this Python library separately.')
        return errors.EXIT_ERROR
    elif not getattr(exc_object, 'internal_error', True):
        report_user_error(exc_info, err_file)
        return errors.EXIT_ERROR
    elif isinstance(exc_object, (OSError, IOError)):
        # Might be nice to catch all of these and show them as something more
        # specific, but there are too many cases at the moment.
        report_user_error(exc_info, err_file)
        return errors.EXIT_ERROR
    else:
        report_bug(exc_info, err_file)
        return errors.EXIT_INTERNAL_ERROR


def print_exception(exc_info, err_file):
    exc_type, exc_object, exc_tb = exc_info
    err_file.write("bzr: ERROR: %s.%s: %s\n" % (
        exc_type.__module__, exc_type.__name__, exc_object))
    err_file.write('\n')
    traceback.print_exception(exc_type, exc_object, exc_tb, file=err_file)


# TODO: Should these be specially encoding the output?
def report_user_error(exc_info, err_file, advice=None):
    """Report to err_file an error that's not an internal error.

    These don't get a traceback unless -Derror was given.

    :param exc_info: 3-tuple from sys.exc_info()
    :param advice: Extra advice to the user to be printed following the
        exception.
    """
    err_file.write("bzr: ERROR: %s\n" % (exc_info[1],))
    if advice:
        err_file.write("%s\n" % (advice,))


def report_bug(exc_info, err_file):
    """Report an exception that probably indicates a bug in bzr"""
    from bzrlib.crash import report_bug
    report_bug(exc_info, err_file)


def _flush_stdout_stderr():
    # installed into an atexit hook by bzrlib.initialize()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except IOError, e:
        import errno
        if e.errno in [errno.EINVAL, errno.EPIPE]:
            pass
        else:
            raise


def _flush_trace():
    # run from atexit hook
    global _trace_file
    if _trace_file:
        _trace_file.flush()
