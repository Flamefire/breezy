# Copyright (C) 2010 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test the command implementations."""

import os
import tempfile
import gzip

from bzrlib import tests
from bzrlib.tests.blackbox import ExternalBase

from bzrlib.plugins.fastimport.cmds import (
    _get_source_stream,
    )

from bzrlib.plugins.fastimport.tests import (
    FastimportFeature,
    )


class TestSourceStream(tests.TestCase):

    _test_needs_features = [FastimportFeature]

    def test_get_source_stream_stdin(self):
        # - returns standard in
        self.assertIsNot(None, _get_source_stream("-"))

    def test_get_source_gz(self):
        # files ending in .gz are automatically decompressed.
        fd, filename = tempfile.mkstemp(suffix=".gz")
        f = gzip.GzipFile(fileobj=os.fdopen(fd, "w"), mode='w')
        f.write("bla")
        f.close()
        stream = _get_source_stream(filename)
        self.assertIsNot("bla", stream.read())

    def test_get_source_file(self):
        # other files are opened as regular files.
        fd, filename = tempfile.mkstemp()
        f = os.fdopen(fd, 'w')
        f.write("bla")
        f.close()
        stream = _get_source_stream(filename)
        self.assertIsNot("bla", stream.read())


class TestFastExport(ExternalBase):

    def test_empty(self):
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-export br")[0])

    def test_pointless(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        data = self.run_bzr("fast-export br")[0]
        self.assertTrue(data.startswith('commit refs/heads/master\nmark :1\ncommitter'))

    def test_file(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        data = self.run_bzr("fast-export br br.fi")[0]
        self.assertEquals("", data)
        try:
            self.assertPathExists("br.fi")
        except AttributeError: # bzr < 2.4
            self.failUnlessExists("br.fi")

    def test_tag_rewriting(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        self.assertTrue(tree.branch.supports_tags())
        rev_id = tree.branch.dotted_revno_to_revision_id((1,))
        tree.branch.tags.set_tag("goodTag", rev_id)
        tree.branch.tags.set_tag("bad Tag", rev_id)
        
        # first check --no-rewrite-tag-names
        data = self.run_bzr("fast-export --plain --no-rewrite-tag-names br")[0]
        self.assertNotEqual(-1, data.find("reset refs/tags/goodTag"))
        self.assertEqual(data.find("reset refs/tags/"), data.rfind("reset refs/tags/"))
        
        # and now with --rewrite-tag-names
        data = self.run_bzr("fast-export --plain --rewrite-tag-names br")[0]
        self.assertNotEqual(-1, data.find("reset refs/tags/goodTag"))
        # "bad Tag" should be exported as bad_Tag
        self.assertNotEqual(-1, data.find("reset refs/tags/bad_Tag"))


simple_fast_import_stream = """commit refs/heads/master
mark :1
committer Jelmer Vernooij <jelmer@samba.org> 1299718135 +0100
data 7
initial

"""

class TestFastImportInfo(ExternalBase):

    def test_simple(self):
        self.build_tree_contents([('simple.fi', simple_fast_import_stream)])
        output = self.run_bzr("fast-import-info simple.fi")[0]
        self.assertEquals(output, """Command counts:
\t0\tblob
\t0\tcheckpoint
\t1\tcommit
\t0\tfeature
\t0\tprogress
\t0\treset
\t0\ttag
File command counts:
\t0\tfilemodify
\t0\tfiledelete
\t0\tfilecopy
\t0\tfilerename
\t0\tfiledeleteall
Parent counts:
\t1\tparents-0
\t0\ttotal revisions merged
Commit analysis:
\tno\texecutables
\tno\tseparate authors found
\tno\tsymlinks
\tno\tblobs referenced by SHA
Head analysis:
\t[':1']\trefs/heads/master
Merges:
""")


class TestFastImport(ExternalBase):

    def test_empty(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import empty.fi br")[0])

    def test_file(self):
        tree = self.make_branch_and_tree("br")
        self.build_tree_contents([('file.fi', simple_fast_import_stream)])
        data = self.run_bzr("fast-import file.fi br")[0]
        self.assertEquals(1, tree.branch.revno())


class TestFastImportFilter(ExternalBase):

    def test_empty(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import-filter -")[0])

    def test_default_stdin(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import-filter")[0])
