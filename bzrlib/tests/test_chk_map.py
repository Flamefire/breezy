# Copyright (C) 2008 Canonical Ltd
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

"""Tests for maps built on a CHK versionedfiles facility."""

from bzrlib.chk_map import (
    CHKMap,
    InternalNode,
    LeafNode,
    RootNode,
    ValueNode,
    _deserialise,
    )
from bzrlib.tests import TestCaseWithTransport


class TestCaseWithStore(TestCaseWithTransport):

    def get_chk_bytes(self):
        # The eassiest way to get a CHK store is a development3 repository and
        # then work with the chk_bytes attribute directly.
        repo = self.make_repository(".", format="development3")
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        return repo.chk_bytes

    def _get_map(self, a_dict, maximum_size=0):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, a_dict, maximum_size=maximum_size)
        chkmap = CHKMap(chk_bytes, root_key)
        return chkmap

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as("fulltext")

    def to_dict(self, node, *args):
        return dict(node.iteritems(*args))


class TestMap(TestCaseWithStore):

    def assertHasABMap(self, chk_bytes):
        root_key = ('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',)
        self.assertEqual(
            "chkroot:\n0\n1\na\x00sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b\n",
            self.read_bytes(chk_bytes, root_key))
        self.assertEqual(
            "chkvalue:\nb",
            self.read_bytes(chk_bytes,
                ("sha1:cb29f32e561a1b7f862c38ccfd6bc7c7d892f04b",)))

    def assertHasEmptyMap(self, chk_bytes):
        root_key = ('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',)
        self.assertEqual("chkroot:\n0\n0\n", self.read_bytes(chk_bytes, root_key))

    def test_from_dict_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        self.assertEqual(('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',),
            root_key)
        self.assertHasEmptyMap(chk_bytes)

    def test_from_dict_ab(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a":"b"})
        self.assertEqual(('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',),
            root_key)
        self.assertHasABMap(chk_bytes)

    def test_apply_empty_ab(self):
        # applying a delta (None, "a", "b") to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([(None, "a", "b")])
        self.assertEqual(('sha1:29f1da33ce2323d754485fd308abc5ff17f3856e',),
            new_root)
        self.assertHasABMap(chk_bytes)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_apply_ab_empty(self):
        # applying a delta ("a", None, None) to an empty chkmap generates the
        # same map as from_dict_ab.
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {"a":"b"})
        chkmap = CHKMap(chk_bytes, root_key)
        new_root = chkmap.apply_delta([("a", None, None)])
        self.assertEqual(('sha1:d0826cf765ff45bd602f602ecb0efbe375ea3b50',),
            new_root)
        self.assertHasEmptyMap(chk_bytes)
        # The update should have left us with an in memory root node, with an
        # updated key.
        self.assertEqual(new_root, chkmap._root_node._key)

    def test_iteritems_empty(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes, {})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([], list(chkmap.iteritems()))

    def test_iteritems_two_items(self):
        chk_bytes = self.get_chk_bytes()
        root_key = CHKMap.from_dict(chk_bytes,
            {"a":"content here", "b":"more content"})
        chkmap = CHKMap(chk_bytes, root_key)
        self.assertEqual([("a", "content here"), ("b", "more content")],
            sorted(list(chkmap.iteritems())))

    def test_iteritems_selected_one_of_two_items(self):
        chkmap = self._get_map( {"a":"content here", "b":"more content"})
        self.assertEqual([("a", "content here")],
            sorted(list(chkmap.iteritems(["a"]))))

    def test___len__empty(self):
        chkmap = self._get_map({})
        self.assertEqual(0, len(chkmap))

    def test___len__2(self):
        chkmap = self._get_map({"foo":"bar", "gam":"quux"})
        self.assertEqual(2, len(chkmap))

    def test_max_size_100_bytes_new(self):
        # When there is a 100 byte upper node limit, a tree is formed.
        chkmap = self._get_map({("k1"*50,):"v1", ("k2"*50,):"v2"}, maximum_size=100)
        # We expect three nodes:
        # A root, with two children, and with two key prefixes - k1 to one, and
        # k2 to the other as our node splitting is only just being developed.
        # The maximum size should be embedded
        chkmap._ensure_root()
        self.assertEqual(100, chkmap._root_node.maximum_size)
        self.assertEqual(1, chkmap._root_node._key_width)
        # There should be two child nodes, and prefix of 2(bytes):
        self.assertEqual(2, len(chkmap._root_node._items))
        self.assertEqual("k", chkmap._root_node.unique_serialised_prefix())
        # The actual nodes pointed at will change as serialisers change; so
        # here we test that the key prefix is correct; then load the nodes and
        # check they have the right pointed at key; whether they have the
        # pointed at value inline or not is also unrelated to this test so we
        # don't check that in detail - rather we just check the aggregate
        # value.
        nodes = sorted(chkmap._root_node._items.items())
        ptr1 = nodes[0]
        ptr2 = nodes[1]
        self.assertEqual('k1', ptr1[0])
        self.assertEqual('k2', ptr2[0])
        node1 = _deserialise(chkmap._read_bytes(ptr1[1]), ptr1[1])
        self.assertIsInstance(node1, LeafNode)
        self.assertEqual(1, len(node1))
        self.assertEqual({('k1'*50,): 'v1'}, self.to_dict(node1, chkmap._store))
        node2 = _deserialise(chkmap._read_bytes(ptr2[1]), ptr2[1])
        self.assertIsInstance(node2, LeafNode)
        self.assertEqual(1, len(node2))
        self.assertEqual({('k2'*50,): 'v2'}, self.to_dict(node2, chkmap._store))
        # Having checked we have a good structure, check that the content is
        # still accessible.
        self.assertEqual(2, len(chkmap))
        self.assertEqual({("k1"*50,): "v1", ("k2"*50,): "v2"},
            self.to_dict(chkmap))

    def test_init_root_is_LeafNode_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        self.assertIsInstance(chkmap._root_node, LeafNode)
        self.assertEqual({}, self.to_dict(chkmap))
        self.assertEqual(0, len(chkmap))

    def test_init_and_save_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        key = chkmap._save()
        leaf_node = LeafNode()
        self.assertEqual([key], leaf_node.serialise(chk_bytes))

    def test_map_first_item_new(self):
        chk_bytes = self.get_chk_bytes()
        chkmap = CHKMap(chk_bytes, None)
        chkmap.map(("foo,",), "bar")
        self.assertEqual({('foo,',): 'bar'}, self.to_dict(chkmap))
        self.assertEqual(1, len(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        leaf_node.map(chk_bytes, ("foo,",), "bar")
        self.assertEqual([key], leaf_node.serialise(chk_bytes))

    def test_unmap_last_item_root_is_leaf_new(self):
        chkmap = self._get_map({("k1"*50,): "v1", ("k2"*50,): "v2"})
        chkmap.unmap(("k1"*50,))
        chkmap.unmap(("k2"*50,))
        self.assertEqual(0, len(chkmap))
        self.assertEqual({}, self.to_dict(chkmap))
        key = chkmap._save()
        leaf_node = LeafNode()
        self.assertEqual([key], leaf_node.serialise(chkmap._store))


class TestRootNode(TestCaseWithTransport):

    def test__current_size(self):
        node = RootNode()
        self.assertEqual(15, node._current_size())
        node.add_child("cd", ("sha1:12345",))
        self.assertEqual(29, node._current_size())
        self.assertEqual(29, len(node.serialise()))
        node.add_child("cd", ("sha1:123456",))
        self.assertEqual(30, node._current_size())
        self.assertEqual(30, len(node.serialise()))
        node.remove_child("cd")
        self.assertEqual(15, node._current_size())
        self.assertEqual(15, len(node.serialise()))
        node.set_maximum_size(100)
        self.assertEqual(17, node._current_size())

    def test_serialise_empty(self):
        node = RootNode()
        bytes = node.serialise()
        self.assertEqual("chkroot:\n0\n0\n0\n", bytes)

    def test_add_child_over_limit(self):
        node = RootNode()
        node.set_maximum_size(20)
        node.add_child("abcdef", ("sha1:12345",))
        size = node._current_size()
        self.assertTrue(20 < size)
        self.assertEqual(False, node.add_child("12345", ("sha1:34",)))
        # Nothing should have changed
        self.assertEqual(size, node._current_size())
        self.assertEqual(1, len(node))

    def test_add_child_resets_key(self):
        node = RootNode()
        node._key = ("something",)
        node.add_child("c", ("sha1:1234",))
        self.assertEqual(None, node._key)

    def test_add_child_returns_True(self):
        node = RootNode()
        node._key = ("something",)
        self.assertEqual(True, node.add_child("c", ("sha1:1234",)))

    def test_add_child_increases_len(self):
        node = RootNode()
        node._key = ("something",)
        node.add_child("c", ("sha1:1234",))
        self.assertEqual(1, len(node))

    def test_remove_child_decreases_len(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("c")
        self.assertEqual(0, len(node))

    def test_remove_child_removes_child(self):
        node = RootNode()
        node.add_child("a", ("sha1:4321",))
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("a")
        self.assertEqual({"c":("sha1:1234",)}, node._nodes)

    def test_remove_child_resets_key(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        node._key = ("something",)
        node.remove_child("c")
        self.assertEqual(None, node._key)

    def test_deserialise(self):
        # deserialising from a bytestring & key sets the nodes and the known
        # key.
        node = RootNode()
        node.deserialise("chkroot:\n0\n0\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual({"c": ("sha1:1234",)}, node._nodes)
        self.assertEqual(("foo",), node._key)
        self.assertEqual(1, len(node))
        self.assertEqual(0, node.maximum_size)

    def test_serialise_with_child(self):
        node = RootNode()
        node.add_child("c", ("sha1:1234",))
        bytes = node.serialise()
        # type 0-max-length 1-value key\x00CHK
        self.assertEqual("chkroot:\n0\n0\n1\nc\x00sha1:1234\n", bytes)

    def test_deserialise_max_size(self):
        node = RootNode()
        node.deserialise("chkroot:\n100\n0\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual(100, node.maximum_size)

    def test_deserialise_key_prefix(self):
        node = RootNode()
        node.deserialise("chkroot:\n100\n10\n1\nc\x00sha1:1234\n", ("foo",))
        self.assertEqual(10, node.prefix_width)


class TestValueNode(TestCaseWithTransport):

    def test_deserialise(self):
        node = ValueNode.deserialise("chkvalue:\nfoo bar baz\n")
        self.assertEqual("foo bar baz\n", node.value)

    def test_serialise(self):
        node = ValueNode("b")
        bytes = node.serialise()
        self.assertEqual("chkvalue:\nb", bytes)


class TestLeafNode(TestCaseWithStore):

    def test_current_size_empty(self):
        node = LeafNode()
        self.assertEqual(15, node._current_size())

    def test_current_size_size_changed(self):
        node = LeafNode()
        node.set_maximum_size(10)
        self.assertEqual(16, node._current_size())

    def test_current_size_width_changed(self):
        node = LeafNode()
        node._key_width = 10
        self.assertEqual(16, node._current_size())

    def test_current_size_items(self):
        node = LeafNode()
        base_size = node._current_size()
        node = node.map(("foo bar",), "baz")
        self.assertEqual(base_size + 12, node._current_size())

    def test_deserialise_empty(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n", ("sha1:1234",))
        self.assertEqual(0, len(node))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(("sha1:1234",), node.key())

    def test_deserialise_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("foo bar",), "baz"), (("quux",), "blarh")],
            sorted(node.iteritems()))

    def test_iteritems_selected_one_of_two_items(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        self.assertEqual(2, len(node))
        self.assertEqual([(("quux",), "blarh")],
            sorted(node.iteritems([("quux",), ("qaz",)])))

    def test_key_new(self):
        node = LeafNode()
        self.assertEqual(None, node.key())

    def test_key_after_map(self):
        node = LeafNode.deserialise("chkleaf:\n10\n1\n0\n", ("sha1:1234",))
        node = node.map(("foo bar",), "baz quux")
        self.assertEqual(None, node.key())

    def test_key_after_unmap(self):
        node = LeafNode.deserialise(
            "chkleaf:\n0\n1\n2\nfoo bar\x00baz\nquux\x00blarh\n", ("sha1:1234",))
        node = node.unmap(("foo bar",))
        self.assertEqual(None, node.key())

    def test_map_exceeding_max_size_only_entry_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        result = node.map(None, ("foo bar",), "baz quux")
        self.assertEqual(("foo bar", [("", node)]), result)
        self.assertTrue(10 < node._current_size())

    def test_map_exceeding_max_size_second_entry_early_difference_new(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node.map(None, ("foo bar",), "baz quux")
        prefix, result = list(node.map(None, ("blue",), "red"))
        self.assertEqual("", prefix)
        self.assertEqual(2, len(result))
        split_chars = set([result[0][0], result[1][0]])
        self.assertEqual(set(["f", "b"]), split_chars)
        nodes = dict(result)
        node = nodes["f"]
        self.assertEqual({("foo bar",): "baz quux"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)
        node = nodes["b"]
        self.assertEqual({("blue",): "red"}, self.to_dict(node, None))
        self.assertEqual(10, node.maximum_size)
        self.assertEqual(1, node._key_width)

    def test_map_exceeding_max_size_second_entry_last_octect_changed(self):
        node = LeafNode()
        node.set_maximum_size(10)
        node = node.map(None, ("foo bar",), "baz quux")
        result = node.map(None, ("foo baz",), "red")
        self.assertIsInstance(result, InternalNode)
        # should have copied the data in:
        self.assertEqual(2, len(result))
        self.assertEqual({('foo baz',): 'red', ('foo bar',): 'baz quux'},
            self.to_dict(result))
        self.assertEqual(10, result.maximum_size)
        self.assertEqual(1, result._key_width)

    def test_map_first(self):
        node = LeafNode()
        result = node.map(("foo bar",), "baz quux")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",):"baz quux"}, self.to_dict(node))
        self.assertEqual(1, len(node))

    def test_map_second(self):
        node = LeafNode()
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("bingo",), "bango")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",):"baz quux", ("bingo",):"bango"},
            self.to_dict(node))
        self.assertEqual(2, len(node))

    def test_map_replacement(self):
        node = LeafNode()
        node = node.map(("foo bar",), "baz quux")
        result = node.map(("foo bar",), "bango")
        self.assertEqual(result, node)
        self.assertEqual({("foo bar",): "bango"},
            self.to_dict(node))
        self.assertEqual(1, len(node))

    def test_serialise_empty(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        expected_key = ("sha1:62cc3565b48b0e830216e652cf99c6bd6b05b4b9",)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n0\n", self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_serialise_items(self):
        store = self.get_chk_bytes()
        node = LeafNode()
        node.set_maximum_size(10)
        node = node.map(("foo bar",), "baz quux")
        expected_key = ("sha1:d44cb6f0299b7e047da7f9e98f810e98f1dce1a7",)
        self.assertEqual([expected_key],
            list(node.serialise(store)))
        self.assertEqual("chkleaf:\n10\n1\n1\nfoo bar\x00baz quux\n",
            self.read_bytes(store, expected_key))
        self.assertEqual(expected_key, node.key())

    def test_unique_serialised_prefix_empty_new(self):
        node = LeafNode()
        self.assertEqual("", node.unique_serialised_prefix())
        return

    def test_unique_serialised_prefix_one_item_new(self):
        node = LeafNode()
        result = node.map(None, ("foo bar", "baz"), "baz quux")
        self.assertEqual("foo bar\x00baz", node.unique_serialised_prefix())

    def test_unmap_missing(self):
        node = LeafNode()
        self.assertRaises(KeyError, node.unmap, ("foo bar",))

    def test_unmap_present(self):
        node = LeafNode()
        node = node.map(None, ("foo bar",), "baz quux")
        result = node.unmap(("foo bar",))
        self.assertEqual(result, node)
        self.assertEqual({}, self.to_dict(node))
        self.assertEqual(0, len(node))


class TestInternalNode(TestCaseWithStore):

    def test_add_node_empty_new(self):
        node = InternalNode()
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, ("foo",), "bar")
        node.add_node("foo", child)
        # Note that node isn't strictly valid now as a tree (only one child),
        # but thats ok for this test.
        # The first child defines the node's width:
        self.assertEqual(3, node._node_width)
        # We should be able to iterate over the contents without doing IO.
        self.assertEqual({('foo',): 'bar'}, self.to_dict(node, None))
        # The length should be known:
        self.assertEqual(1, len(node))
        # serialising the node should serialise the child and the node.
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        child_key = child.serialise(chk_bytes)[0]
        self.assertEqual(
            [child_key, ('sha1:db23b260c2bf46bf7446c39f91668900a2491610',)],
            keys)
        # We should be able to access deserialised content.
        bytes = self.read_bytes(chk_bytes, keys[1])
        node = _deserialise(bytes, keys[1])
        self.assertEqual(1, len(node))
        self.assertEqual({('foo',): 'bar'}, self.to_dict(node, chk_bytes))
        self.assertEqual(3, node._node_width)

    def test_add_node_resets_key_new(self):
        node = InternalNode()
        child = LeafNode()
        child.set_maximum_size(100)
        child.map(None, ("foo",), "bar")
        node.add_node("foo", child)
        chk_bytes = self.get_chk_bytes()
        keys = list(node.serialise(chk_bytes))
        self.assertEqual(keys[1], node._key)
        node.add_node("fos", child)
        self.assertEqual(None, node._key)

#    def test_add_node_empty_oversized_one_ok_new(self):
#    def test_add_node_one_oversized_second_kept_minimum_fan(self):
#    def test_add_node_two_oversized_third_kept_minimum_fan(self):
#    def test_add_node_one_oversized_second_splits_errors(self):

    def test_add_node_empty_oversized_no_common_sets_prefix(self):
        # adding a node with two children that is oversized will generate two
        # new leaf nodes, and a prefix width that cuts one byte off the longest
        # key (because that is sufficient to guarantee a split
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(None, ("foo bar",), "baz")
        overpacked.map(None, ("strange thing",), "it is")
        # at this point, map returned a new internal node that is already
        # packed, but that should have preserved the old node due to the 
        # functional idioms.. check to be sure:
        self.assertTrue(overpacked.maximum_size < overpacked._current_size())
        node = InternalNode()
        # We're not testing that the internal node rebalances yet
        node.set_maximum_size(0)
        node._add_node(overpacked)
        # 13 is the length of strange_thing serialised; as there is no node size
        # set, we pack the internal node as densely as possible.
        self.assertEqual(13, node._node_width)
        self.assertEqual(set(["strange thing", "foo bar\x00\x00\x00\x00\x00\x00"]),
            set(node._items.keys()))
        self.assertEqual(2, len(node))
        self.assertEqual({('strange thing',): 'it is'},
            self.to_dict(node._items["strange thing"]))
        self.assertEqual({('foo bar',): 'baz'},
            self.to_dict(node._items["foo bar\x00\x00\x00\x00\x00\x00"]))

    def test_iteritems_empty_new(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems(None)))

    def test_iteritems_two_children(self):
        node = InternalNode()
        leaf1 = LeafNode()
        leaf1.map(None, ('foo bar',), 'quux')
        leaf2 = LeafNode()
        leaf2 = LeafNode()
        leaf2.map(None, ('strange',), 'beast')
        node._items['foo ba'] = leaf1
        node._items['strang'] = leaf2
        self.assertEqual([(('foo bar',), 'quux'), (('strange',), 'beast')],
            sorted(node.iteritems()))

    def test_iteritems_two_children_partial(self):
        node = InternalNode()
        leaf2 = LeafNode()
        leaf2 = LeafNode()
        leaf2.map(None, ('strange',), 'beast')
        # This sets up a path that should not be followed - it will error if
        # the code tries to.
        node._items['foo ba'] = None
        node._items['strang'] = leaf2
        node._node_width = 6
        self.assertEqual([(('strange',), 'beast')],
            sorted(node.iteritems([('strange',), ('weird',)])))

    def test_iteritems_partial_empty(self):
        node = InternalNode()
        self.assertEqual([], sorted(node.iteritems([('missing',)])))

    def test_map_to_existing_child(self):
        # mapping a new key which is in a child of an internal node maps
        # recursively.
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(None, ("foo bar",), "baz")
        node = overpacked.map(None, ("foo baz",), "it is")
        self.assertIsInstance(node, InternalNode)
        # Now, increase the maximum size limit on the subnode for foo bar
        child = node._items[node._serialised_key(("foo bar",))]
        child.set_maximum_size(200)
        # And map a new key into node, which will land in the same child node
        result = node.map(None, ("foo bar baz",), "new value")
        self.assertTrue(result is node)
        self.assertEqual(3, len(result))
        self.assertEqual(2, len(child))
        self.assertEqual({('foo bar',): 'baz',
            ('foo bar baz',): 'new value', ('foo baz',): 'it is'},
            self.to_dict(node))

    def test_map_to_existing_child_exceed_child_size_not_internal_size(self):
        # mapping a new key which is in a child of an internal node maps
        # recursively, and when the child splits that is accomodated within the
        # internal node if there is room for another child pointer.
        overpacked = LeafNode()
        # 3 pointers, 7 bytes offset, 45 byte pointers, + prelude.
        overpacked.set_maximum_size(180)
        overpacked.map(None, ("foo bar",), "baz " * 40)
        node = overpacked.map(None, ("foo baz",), "itis" * 40)
        self.assertIsInstance(node, InternalNode)
        # And map a new key into node, which will land in the same child path
        # within node, but trigger a spill event on the child, and should end
        # up with 3 pointers in node (as the pointers can fit in the node
        # space.
        result = node.map(None, ("foo bar baz",), "new " * 60)
        self.assertTrue(result is node)
        self.assertEqual(3, len(result))
        # We should have one child for foo bar
        child = node._items[node._serialised_key(("foo bar\x00",))]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        # And one for 'foo bar '
        child = node._items[node._serialised_key(("foo bar ",))]
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('foo bar',): 'baz ' * 60,
            ('foo bar baz',): 'new ' * 60,
            ('foo baz',): 'itis' * 60},
            self.to_dict(node))

    def test_map_to_new_child_new(self):
        chkmap = self._get_map({('k1',):'foo', ('k2',):'bar'}, maximum_size=10)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(2,
            len([value for value in node._items.values()
                if type(value) == tuple]))
        # now, mapping to k3 should add a k3 leaf
        prefix, nodes = node.map(None, ('k3',), 'quux')
        self.assertEqual("k", prefix)
        self.assertEqual([("", node)], nodes)
        # check new child details
        child = node._items['k3']
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('k3',): 'quux'}, self.to_dict(child, None))
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k2',): 'bar', ('k3',): 'quux'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - k3 and the internal
        # node.
        keys = list(node.serialise(chkmap._store))
        child_key = child.serialise(chkmap._store)[0]
        self.assertEqual([child_key, keys[1]], keys)

    def test_map_to_child_child_splits_new(self):
        chkmap = self._get_map({('k1',):'foo', ('k22',):'bar'}, maximum_size=10)
        # Check for the canonical root value for this tree:
        self.assertEqual(('sha1:d3f06fc03d8f50845894d8d04cc5a3f47e62948d',),
            chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # Ensure test validity: nothing paged in below the root.
        self.assertEqual(2,
            len([value for value in node._items.values()
                if type(value) == tuple]))
        # now, mapping to k23 causes k22 ('k2' in node) to split into k22 and
        # k23, which for simplicity in the current implementation generates
        # a new internal node between node, and k22/k23.
        prefix, nodes = node.map(chkmap._store, ('k23',), 'quux')
        self.assertEqual("k", prefix)
        self.assertEqual([("", node)], nodes)
        # check new child details
        child = node._items['k2']
        self.assertIsInstance(child, InternalNode)
        self.assertEqual(2, len(child))
        self.assertEqual({('k22',): 'bar', ('k23',): 'quux'},
            self.to_dict(child, None))
        self.assertEqual(None, child._key)
        self.assertEqual(10, child.maximum_size)
        self.assertEqual(1, child._key_width)
        self.assertEqual(3, child._node_width)
        # Check overall structure:
        self.assertEqual(3, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k22',): 'bar', ('k23',): 'quux'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - although k22 hasn't
        # changed because its a special corner case (splitting on with only one
        # key leaves one node unaltered), in general k22 is serialised, so we
        # expect k22, k23, the new internal node, and node, to be serialised.
        keys = list(node.serialise(chkmap._store))
        child_key = child._key
        k22_key = child._items['k22']._key
        k23_key = child._items['k23']._key
        self.assertEqual([k22_key, k23_key, child_key, keys[-1]], keys)
        self.assertEqual(('sha1:d68cd97c95e847d3dc58c05537aa5fdcdf2cf5da',),
            keys[-1])

    def test_unmap_k23_from_k1_k22_k23_gives_k1_k22_tree_new(self):
        chkmap = self._get_map(
            {('k1',):'foo', ('k22',):'bar', ('k23',): 'quux'}, maximum_size=10)
        # Check we have the expected tree.
        self.assertEqual(('sha1:d68cd97c95e847d3dc58c05537aa5fdcdf2cf5da',),
            chkmap._root_node)
        chkmap._ensure_root()
        node = chkmap._root_node
        # unmapping k23 should give us a root, with k1 and k22 as direct
        # children.
        result = node.unmap(chkmap._store, ('k23',))
        # check the pointed-at object within node - k2 should now point at the
        # k22 leaf (which should not even have been paged in).
        ptr = node._items['k2']
        self.assertIsInstance(ptr, tuple)
        child = _deserialise(self.read_bytes(chkmap._store, ptr), ptr)
        self.assertIsInstance(child, LeafNode)
        self.assertEqual(1, len(child))
        self.assertEqual({('k22',): 'bar'},
            self.to_dict(child, None))
        # Check overall structure is instact:
        self.assertEqual(2, len(chkmap))
        self.assertEqual({('k1',): 'foo', ('k22',): 'bar'},
            self.to_dict(chkmap))
        # serialising should only serialise the new data - the root node.
        keys = list(node.serialise(chkmap._store))
        self.assertEqual([keys[-1]], keys)
        self.assertEqual(('sha1:d3f06fc03d8f50845894d8d04cc5a3f47e62948d',), keys[-1])

    def test_unmap_second_last_shrinks_to_other_branch(self):
        # unmapping the second last child of an internal node downgrades it to
        # a leaf node.
        overpacked = LeafNode()
        overpacked.set_maximum_size(10)
        overpacked.map(None, ("foo bar",), "baz")
        node = overpacked.map(None, ("strange thing",), "it is")
        self.assertIsInstance(node, InternalNode)
        result = node.unmap(("foo bar",))
        self.assertIsInstance(result, LeafNode)
        self.assertEqual({("strange thing",): "it is"}, self.to_dict(result))


# leaf:
# map -> fits - done
# map -> doesn't fit - shrink from left till fits
#        key data to return: the common prefix, new nodes.

# unmap -> how to tell if siblings can be combined.
#          combing leaf nodes means expanding the prefix to the left; so gather the size of
#          all the leaf nodes addressed by expanding the prefix by 1; if any adjacent node
#          is an internal node, we know that that is a dense subtree - can't combine.
#          otherwise as soon as the sum of serialised values exceeds the split threshold
#          we know we can't combine - stop.
# unmap -> key return data - space in node, common prefix length? and key count
# internal: 
# variable length prefixes? -> later start with fixed width to get something going
# map -> fits - update pointer to leaf
#        return [prefix and node] - seems sound.
# map -> doesn't fit - find unique prefix and shift right
#        create internal nodes for all the partitions, return list of unique
#        prefixes and nodes.
# map -> new prefix - create a leaf
# unmap -> if child key count 0, remove
# unmap -> return space in node, common prefix length? (why?), key count
# map:
# map, if 1 node returned, use it, otherwise make an internal and populate.
# map - unmap - if empty, use empty leafnode (avoids special cases in driver
# code)
# map inits as empty leafnode.
# tools: 
# visualiser


# how to handle:
# AA, AB, AC, AD, BA
# packed internal node - ideal:
# AA, AB, AC, AD, BA
# single byte fanout - A,B,   AA,AB,AC,AD,     BA
# build order's:
# BA
# AB - split, but we want to end up with AB, BA, in one node, with 
# 1-4K get0
