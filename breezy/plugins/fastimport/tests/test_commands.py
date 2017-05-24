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

from __future__ import absolute_import

import os
import re
import tempfile
import gzip

from .... import tests
from ....tests.blackbox import ExternalBase

from ..cmds import (
    _get_source_stream,
    )

from . import (
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


fast_export_baseline_data = """commit refs/heads/master
mark :1
committer
data 15
add c, remove b
M 644 inline a
data 13
test 1
test 3
M 644 inline c
data 6
test 4
commit refs/heads/master
mark :2
committer
data 14
modify a again
from :1
M 644 inline a
data 20
test 1
test 3
test 5
commit refs/heads/master
mark :3
committer
data 5
add d
from :2
M 644 inline d
data 6
test 6
"""

class TestFastExport(ExternalBase):

    _test_needs_features = [FastimportFeature]

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

    def test_no_tags(self):
        tree = self.make_branch_and_tree("br")
        tree.commit("pointless")
        self.assertTrue(tree.branch.supports_tags())
        rev_id = tree.branch.dotted_revno_to_revision_id((1,))
        tree.branch.tags.set_tag("someTag", rev_id)

        data = self.run_bzr("fast-export --plain --no-tags br")[0]
        self.assertEqual(-1, data.find("reset refs/tags/someTag"))

    def test_baseline_option(self):
        tree = self.make_branch_and_tree("bl")

        # Revision 1
        file('bl/a', 'w').write('test 1')
        tree.add('a')
        tree.commit(message='add a')

        # Revision 2
        file('bl/b', 'w').write('test 2')
        file('bl/a', 'a').write('\ntest 3')
        tree.add('b')
        tree.commit(message='add b, modify a')

        # Revision 3
        file('bl/c', 'w').write('test 4')
        tree.add('c')
        tree.remove('b')
        tree.commit(message='add c, remove b')

        # Revision 4
        file('bl/a', 'a').write('\ntest 5')
        tree.commit(message='modify a again')

        # Revision 5
        file('bl/d', 'w').write('test 6')
        tree.add('d')
        tree.commit(message='add d')

        # This exports the baseline state at Revision 3,
        # followed by the deltas for 4 and 5
        data = self.run_bzr("fast-export --baseline -r 3.. bl")[0]
        data = re.sub('committer.*', 'committer', data)
        self.assertEquals(fast_export_baseline_data, data)

        # Also confirm that --baseline with no args is identical to full export
        data1 = self.run_bzr("fast-export --baseline bl")[0]
        data2 = self.run_bzr("fast-export bl")[0]
        self.assertEquals(data1, data2)

simple_fast_import_stream = """commit refs/heads/master
mark :1
committer Jelmer Vernooij <jelmer@samba.org> 1299718135 +0100
data 7
initial

"""

class TestFastImportInfo(ExternalBase):

    _test_needs_features = [FastimportFeature]

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

    _test_needs_features = [FastimportFeature]

    def test_empty(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import empty.fi br")[0])

    def test_file(self):
        tree = self.make_branch_and_tree("br")
        self.build_tree_contents([('file.fi', simple_fast_import_stream)])
        data = self.run_bzr("fast-import file.fi br")[0]
        self.assertEquals(1, tree.branch.revno())

    def test_missing_bytes(self):
        self.build_tree_contents([('empty.fi', """
commit refs/heads/master
mark :1
committer
data 15
""")])
        self.make_branch_and_tree("br")
        self.run_bzr_error(['brz: ERROR: 4: Parse error: line 4: Command commit is missing section committer\n'], "fast-import empty.fi br")


class TestFastImportFilter(ExternalBase):

    _test_needs_features = [FastimportFeature]

    def test_empty(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import-filter -")[0])

    def test_default_stdin(self):
        self.build_tree_contents([('empty.fi', "")])
        self.make_branch_and_tree("br")
        self.assertEquals("", self.run_bzr("fast-import-filter")[0])
