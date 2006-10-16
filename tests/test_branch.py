# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirTestProviderAdapter, BzrDirFormat
from bzrlib.repository import Repository
from bzrlib.trace import mutter

import os

import svn.core, svn.client

import format
from repository import MAPPING_VERSION
from tests import TestCaseWithSubversionRepository

class WorkingSubversionBranch(TestCaseWithSubversionRepository):
    def test_num_revnums(self):
        repos_url = self.make_client('a', 'dc')
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        self.assertEqual(None, branch.last_revision())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        repos = bzrdir.open_repository()

        self.assertEqual("svn-v%d:1@%s-" % (MAPPING_VERSION, repos.uuid), 
                branch.last_revision())

        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                branch.last_revision())

    def test_revision_history(self):
        repos_url = self.make_client('a', 'dc')

        branch = Branch.open("svn+"+repos_url)
        self.assertEqual([], branch.revision_history())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        
        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual(["svn-v%d:1@%s-" % (MAPPING_VERSION, repos.uuid)], 
                branch.revision_history())

        self.build_tree({'dc/foo': "data34"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual([
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repos.uuid), 
            "svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)],
            branch.revision_history())

    def test_get_nick(self):
        repos_url = self.make_client('a', 'dc')

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)

        self.assertIs(None, branch.nick)

    def test_fetch_replace(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6f95bc5c-e18d-4021-aca8-49ed51dbcb75

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-30T12:41:25.270824Z
PROPS-END

Revision-number: 1
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:26.117512Z
PROPS-END

Node-path: trunk
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Node-path: trunk/hosts
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 4
Text-content-md5: 771ec3328c29d17af5aacf7f895dd885
Content-length: 14

PROPS-END
hej1

Revision-number: 2
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:27.130044Z
PROPS-END

Node-path: trunk/hosts
Node-kind: file
Node-action: change
Text-content-length: 4
Text-content-md5: 6c2479dbb342b8df96d84db7ab92c412
Content-length: 4

hej2

Revision-number: 3
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:28.114350Z
PROPS-END

Node-path: trunk/hosts
Node-kind: file
Node-action: change
Text-content-length: 4
Text-content-md5: 368cb8d3db6186e2e83d9434f165c525
Content-length: 4

hej3

Revision-number: 4
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:29.129563Z
PROPS-END

Node-path: branches
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 5
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:31.130508Z
PROPS-END

Node-path: branches/foobranch
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 4
Node-copyfrom-path: trunk


Revision-number: 6
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:33.129149Z
PROPS-END

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: delete

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: add
Node-copyfrom-rev: 2
Node-copyfrom-path: trunk/hosts




Revision-number: 7
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:34.136423Z
PROPS-END

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: change
Text-content-length: 8
Text-content-md5: 0e328d3517a333a4879ebf3d88fd82bb
Content-length: 8

foohosts""")
        os.mkdir("new")

        url = "dumpfile/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()

        uuid = "6f95bc5c-e18d-4021-aca8-49ed51dbcb75"
        tree = newbranch.repository.revision_tree(
                "svn-v%d:7@%s-branches%%2ffoobranch" % (MAPPING_VERSION, uuid))

        weave = tree.get_weave(tree.inventory.path2id("hosts"))
        self.assertEqual([
            'svn-v%d:6@%s-branches%%2ffoobranch' % (MAPPING_VERSION, uuid), 
            'svn-v%d:7@%s-branches%%2ffoobranch' % (MAPPING_VERSION, uuid)],
                          weave.versions())
 

    def test_fetch_odd(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #4

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #5

        self.build_tree({'dc/branches/foobranch/hosts': 'foohosts'})
        self.client_commit("dc", "foohosts") #6

        os.mkdir("new")

        url = "svn+"+repos_url+"/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()

        uuid = olddir.open_repository().uuid
        tree = newbranch.repository.revision_tree(
                "svn-v%d:6@%s-branches%%2ffoobranch" % (MAPPING_VERSION, uuid))

        weave = tree.get_weave(tree.inventory.path2id("hosts"))
        self.assertEqual([
            'svn-v%d:1@%s-trunk' % (MAPPING_VERSION, uuid), 
            'svn-v%d:2@%s-trunk' % (MAPPING_VERSION, uuid), 
            'svn-v%d:3@%s-trunk' % (MAPPING_VERSION, uuid), 
            'svn-v%d:6@%s-branches%%2ffoobranch' % (MAPPING_VERSION, uuid)],
                          weave.versions())
 
    def test_fetch_branch(self):
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        olddir = BzrDir.open("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_ghost_workingtree(self):
        # Looks like bazaar has trouble creating a working tree of a 
        # revision that has ghost parents
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_set_prop("sc", "bzr:merge", "some-ghost\n")
        self.client_commit("sc", "foo")

        olddir = BzrDir.open("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')
        newdir.open_repository().get_revision(
                newdir.open_branch().last_revision())
        newdir.open_repository().get_revision_inventory(
                newdir.open_branch().last_revision())
