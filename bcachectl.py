#!/usr/bin/env python3
"""
Helper tool to show bcache hierarchy
"""
#
# :dotsctl:
#   destdir: ~/bin/
#   dpkg:
#     - python3-yaml
# ...


# /sys/class/block/bcache${N}/bcache/
#   cache -> .../fs/bcache/${cset.uuid}
#   cache/bdev${N}/ -> .../$(block)/bcache/
#   cache/cache$(N) -> .../$(block)/bcache/
#
# bcache-super-show /dev/nvme1n1p1 | grep cset.uuid
# echo $(cset.uuid) >/sys/block/bcache0/bcache/detach
# while not done
#   cat /sys/block/bcache0/bcache/dirty_data
# dmesg: bcache: cached_dev_detach_finish() Caching disabled for sdb4
#
# fdisk
# make-bcache -C /dev/nvme0n1p1
# bcache-super-show /dev/nvme1n1p1 | grep cset.uuid
# echo $(cset.uuid} > /sys/block/bcache0/bcache/attach
#
# echo writeback > /sys/class/block/bcache0/bcache/cache_mode
# echo 0 > /sys/class/block/bcache0/bcache/sequential_cutoff


import argparse
import glob
import os


def argparser():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument(
        "--internal_tests",
        action="store_true",
        default=False,
        help="Run the internal tests"
    )
    args.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Increase verbosity"
    )

    # Trie testing:
    # args.add_argument(
    #     "-f", "--find",
    #     help="Find match"
    # )
    # args.add_argument(
    #     "words",
    #     nargs="*",
    #     help="Words to add to trie"
    # )

    r = args.parse_args()
    return r


class Trie:
    """Implement a Trie structure

    >>> t = Trie()
    >>> t.insert("larry")
    >>> t.insert("moe")
    >>> t.insert("curly")

    >>> len(t.children) == 3
    True

    >>> sorted(t.prefixes())
    ['c', 'l', 'm']

    >>> sorted(t.prefixes(minlen=2))
    ['cu', 'la', 'mo']

    >>> t.insert("clinton")
    >>> sorted(t.prefixes())
    ['cl', 'cu', 'l', 'm']

    >>> t.find("m")
    'moe'

    >>> found = t.find("c")
    >>> found[0]
    'c'
    >>> sorted(found[1].prefixes())
    ['l', 'u']

    >>> t.find("z")
    False

    """

    def __init__(self):
        self.children = {}

    def insert(self, key):
        """Insert a new key into the Trie"""
        ch = key[0]
        if ch not in self.children:
            self.children[ch] = Trie()

        if len(key) > 1:
            self.children[ch].insert(key[1:])

    def find(self, key):
        """Given a unique prefix, return the full value

        >>> t = Trie()
        >>> t.insert("ab1")
        >>> t.insert("ab2")
        >>> found = t.find("a")

        >>> found[0]
        'ab'

        >>> sorted(found[1].prefixes())
        ['1', '2']
        """
        # We are now just looking for the full key
        if key is None:
            # .. this is the final depth
            if len(self.children) == 0:
                return ''

            # .. and are there are multiple matches?
            if len(self.children) > 1:
                return ('', self)

            # Recurse deeper
            ch, child = list(self.children.items())[0]
            tail = child.find(key)
            if isinstance(tail, str):
                return ch + tail
            if isinstance(tail, bool):
                return tail

            child = tail[1]
            tail = tail[0]

            return (ch + tail, child)

        ch = key[0]
        if ch not in self.children:
            # A failed find
            return False

        child = self.children[ch]

        # is this is the last char of the search key?
        if len(key) == 1:
            tail = child.find(None)
        else:
            tail = child.find(key[1:])

        if isinstance(tail, str):
            return ch + tail

        if isinstance(tail, bool):
            return tail

        child = tail[1]
        tail = tail[0]

        return (ch + tail, child)

    def shorten(self, key, minlen=1):
        """Given a full value, return the unique prefix

        >>> t = Trie()
        >>> t.insert("12345678")

        >>> t.shorten("12345678")
        '1'
        >>> t.shorten("12345678", minlen=2)
        '12'

        >>> t.insert("1234abcd")

        >>> t.shorten("12345")
        False

        >>> t.shorten("12345678")
        '12345'
        """

        items = []
        this = self
        while len(items) < len(key):
            ch = key[len(items)]
            if ch not in this.children:
                return False
            this = this.children[ch]
            items.append(this)

        # The key didnt find one complete item
        if len(items[-1].children):
            return False

        offset = len(items) - 2
        while offset >= 0:
            if len(items[offset].children) == 1:
                offset -= 1
            else:
                offset += 2
                if offset < minlen:
                    offset = minlen
                return key[:offset]

        # We never had a collision, so the key is unique at the start
        return key[0:minlen]

    def prefixes(self, prefix=None, minlen=0):
        """Return a list of unique prefixes"""
        if prefix is None:
            prefix = ""

        if len(self.children) == 0:
            # definitely terminal
            return set([prefix])

        if len(self.children) == 1:
            # dont return if we need more chars
            if len(prefix) >= minlen:
                return set([prefix])

        found = set()
        for ch, v in self.children.items():
            found.update(v.prefixes(prefix + ch, minlen=minlen))

        return found


class Bcache:
    ids = Trie()

    def __init__(self):
        self.path = None
        self.type = None
        self._id = None
        self._parent = None

    def __str__(self):
        # TODO:
        # This is hard coding the indenting expectations
        if self._parent is None:
            width = 9
        else:
            width = 6

        return f"{self.type:{width}} {self.id} {self.path}"

    @property
    def id(self):
        if self._id is None:
            return str(self._id)
        return self.ids.shorten(self._id, minlen=4)

    @id.setter
    def id(self, val):
        self._id = val
        self.ids.insert(val)

    @property
    def parent(self):
        if self._parent is None:
            return str(self._parent)
        return self.ids.shorten(self._parent, minlen=4)

    @parent.setter
    def parent(self, val):
        self._parent = val
        self.ids.insert(val)

    @classmethod
    def _find_fs_bcache(cls):
        objects = []
        os.chdir("/sys/fs/bcache")
        files = glob.glob("*")
        for file in files:
            if not os.path.isdir(file):
                continue

            obj = cls()
            obj.type = "cset"
            obj.id = file

            if os.path.islink(f"{file}/bdev0/dev"):
                obj.path = os.readlink(f"{file}/bdev0/dev").split("/")[-1]

            objects.append(obj)

            for bdev in glob.glob(f"{file}/bdev*"):
                if not os.path.islink(bdev):
                    continue
                obj = cls()
                obj.type = bdev.split("/")[-1]
                obj.parent = file
                with open(f"{bdev}/backing_dev_name") as f:
                    obj.path = f.readline().strip()
                with open(f"{bdev}/backing_dev_uuid") as f:
                    obj.id = f.readline().strip()
                objects.append(obj)

            for cache in glob.glob(f"{file}/cache*"):
                if not os.path.islink(cache):
                    continue
                obj = cls()
                obj.type = cache.split("/")[-1]
                obj.parent = file
                obj.path = os.readlink(cache).split("/")[-2]
                # TODO: how to get cache uuid without reading the superblock?
                obj.id = "Null"
                objects.append(obj)

        return objects

    @classmethod
    def _find_block(cls):
        objects = []
        os.chdir("/sys/class/block")
        files = glob.glob("*")
        for file in files:
            if not os.path.exists(f"{file}/bcache"):
                continue

            if os.path.islink(f"{file}/bcache"):
                obj = cls()
                obj.type = "cset"
                obj.path = file
                objects.append(obj)
                continue

            obj = cls()
            obj.type = "unk"
            obj.path = file
            objects.append(obj)

        return objects

    @classmethod
    def find(cls):
        objects = []
        objects += cls._find_fs_bcache()
        # objects += cls._find_block()
        return objects


def test_internal():
    import doctest
    doctest.testmod()


def main():
    args = argparser()
    if args.internal_tests:
        return test_internal()

    objects = Bcache.find()
    parents = []
    children = {}

    for i in objects:
        if i._parent is None:
            parents.append(i)
            continue

        if i.parent not in children:
            children[i.parent] = []

        children[i.parent].append(i)

    for parent in parents:
        print(parent)
        nr = len(children[parent.id])
        for child in children[parent.id]:
            if nr == 1:
                prefix = "└─"
            else:
                prefix = "├─"
            nr -= 1

            print(prefix, child)

    # print(yaml.dump(Bcache.ids))

    # Trie testing:
    # trie = Trie()
    # for word in args.words:
    #     trie.insert(word)

    # if args.verbose:
    #     print(yaml.dump(trie))

    # prefixes = trie.prefixes(minlen=3)
    # for prefix in sorted(prefixes):
    #     print(prefix)

    # if args.find:
    #     print()
    #     found = trie.find(args.find)
    #     if isinstance(found, str):
    #         print(found)
    #         return

    #     if isinstance(found, bool):
    #         print(found)
    #         return

    #     tail = found[0]
    #     child = found[1]
    #     prefixes = child.prefixes()
    #     for prefix in sorted(prefixes):
    #         print(tail, prefix)


if __name__ == "__main__":
    main()
