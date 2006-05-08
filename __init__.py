# Simple SVN pull / push functionality for bzr
# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>
# Published under the GNU GPL

"""
Support for foreign branches (Subversion)
"""
import sys
import os.path
import transport
import format
import branch

sys.path.append(os.path.dirname(__file__))

from bzrlib.transport import register_transport
register_transport('svn', transport.SvnTransport)

from bzrlib.bzrdir import BzrDirFormat
BzrDirFormat.register_format(format.SvnFormat())

def test_suite():
    from unittest import TestSuite, TestLoader
    import tests.test_repos

    suite = TestSuite()

    suite.addTest(TestLoader().loadTestsFromModule(tests.test_repos))

    return suite

