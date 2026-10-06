"""An OLE2 compound-file writer and a VBA project builder for synthetic samples (spec §11.1).

Real Office macro files, legacy .xls workbooks and Outlook .msg emails are OLE compound files.
Rather than commit binary samples, the fixture builder writes them at test time from readable
Python: ``build_ole`` lays out streams (mini stream for small ones), and ``vba_project`` writes
an MS-OVBA project (``dir`` stream + module streams) whose compressed containers use literal
tokens only, which every MS-OVBA reader (olevba included) decompresses.

Version 3 files, 512-byte sectors, 64-byte mini sectors, cutoff 4096; no DIFAT (≤ 109 FAT
sectors, i.e. files up to ~7 MB, far more than fixtures need).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from itertools import pairwise

SECTOR = 512
MINI = 64
CUTOFF = 4096
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


@dataclass
class _Node:
    name: str
    kind: int  # 1 storage, 2 stream, 5 root
    data: bytes = b""
    children: dict[str, _Node] = field(default_factory=dict)
    sid: int = 0
    start: int = ENDOFCHAIN
    left: int = NOSTREAM
    right: int = NOSTREAM
    child: int = NOSTREAM


def _tree(streams: dict[str, bytes]) -> _Node:
    root = _Node("Root Entry", 5)
    for path, data in streams.items():
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.children.setdefault(part, _Node(part, 1))
        node.children[parts[-1]] = _Node(parts[-1], 2, data)
    return root


def _flatten(root: _Node) -> list[_Node]:
    order: list[_Node] = []

    def walk(n: _Node) -> None:
        n.sid = len(order)
        order.append(n)
        kids = sorted(n.children.values(), key=lambda c: (len(c.name), c.name.upper()))
        for k in kids:
            walk(k)
        # children as a right-leaning chain (all black): valid for readers, which only follow
        # the left/right/child links
        if kids:
            n.child = kids[0].sid
            for a, b in pairwise(kids):
                a.right = b.sid

    walk(root)
    return order


def _chain(fat: list[int], start: int, count: int) -> None:
    for i in range(count):
        fat[start + i] = start + i + 1 if i < count - 1 else ENDOFCHAIN


def build_ole(streams: dict[str, bytes]) -> bytes:
    """Streams by path ("VBA/dir", "PROJECT") → the bytes of a compound file."""
    root = _tree(streams)
    nodes = _flatten(root)
    small = [n for n in nodes if n.kind == 2 and len(n.data) < CUTOFF]
    large = [n for n in nodes if n.kind == 2 and len(n.data) >= CUTOFF]

    mini_stream = bytearray()
    mini_fat: list[int] = []
    for n in small:
        if not n.data:
            n.start = ENDOFCHAIN
            continue
        count = -(-len(n.data) // MINI)
        n.start = len(mini_fat)
        mini_fat.extend([0] * count)
        _chain(mini_fat, n.start, count)
        mini_stream += n.data + b"\0" * (count * MINI - len(n.data))

    def sectors(nbytes: int) -> int:
        return -(-nbytes // SECTOR)

    dir_bytes = len(nodes) * 128
    n_dir = sectors(dir_bytes)
    n_minifat = sectors(len(mini_fat) * 4)
    n_ministream = sectors(len(mini_stream))
    n_large = [sectors(len(n.data)) for n in large]
    body = n_dir + n_minifat + n_ministream + sum(n_large)
    n_fat = 1
    while n_fat * (SECTOR // 4) < body + n_fat:
        n_fat += 1
    assert n_fat <= 109, "fixture too large for a FAT without DIFAT"

    total = n_fat + body
    fat = [FREESECT] * (n_fat * (SECTOR // 4))
    for i in range(n_fat):
        fat[i] = FATSECT
    pos = n_fat
    dir_start = pos
    _chain(fat, pos, n_dir)
    pos += n_dir
    minifat_start = pos if n_minifat else ENDOFCHAIN
    _chain(fat, pos, n_minifat)
    pos += n_minifat
    ministream_start = pos if n_ministream else ENDOFCHAIN
    _chain(fat, pos, n_ministream)
    pos += n_ministream
    for n, count in zip(large, n_large, strict=True):
        n.start = pos
        _chain(fat, pos, count)
        pos += count
    assert pos == total
    root.start = ministream_start
    root.data = bytes(mini_stream)

    header = bytearray(SECTOR)
    header[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into(
        "<HHHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9, 6
    )  # minor, major, byte order, sector shift, mini sector shift
    struct.pack_into("<I", header, 40, 0)  # directory sectors (0 in v3)
    struct.pack_into("<I", header, 44, n_fat)
    struct.pack_into("<I", header, 48, dir_start)
    struct.pack_into("<I", header, 52, 0)
    struct.pack_into("<I", header, 56, CUTOFF)
    struct.pack_into("<I", header, 60, minifat_start)
    struct.pack_into("<I", header, 64, n_minifat)
    struct.pack_into("<I", header, 68, ENDOFCHAIN)
    struct.pack_into("<I", header, 72, 0)
    for i in range(109):
        struct.pack_into("<I", header, 76 + 4 * i, i if i < n_fat else FREESECT)

    out = bytearray(header)
    out += struct.pack(f"<{len(fat)}I", *fat)
    d = bytearray()
    for n in nodes:
        e = bytearray(128)
        name = n.name.encode("utf-16-le") + b"\0\0"
        e[0 : len(name)] = name
        struct.pack_into("<H", e, 64, len(name))
        e[66] = n.kind
        e[67] = 1  # black
        struct.pack_into("<III", e, 68, n.left, n.right, n.child)
        size = len(n.data) if n.kind in (2, 5) else 0
        start = n.start if n.kind in (2, 5) else 0
        struct.pack_into("<I", e, 116, start if size or n.kind == 5 else ENDOFCHAIN)
        struct.pack_into("<Q", e, 120, size)
        d += e
    d += b"\0" * (n_dir * SECTOR - len(d))
    # unused directory slots must be empty entries with no siblings
    for i in range(len(nodes), n_dir * (SECTOR // 128)):
        struct.pack_into("<III", d, i * 128 + 68, NOSTREAM, NOSTREAM, NOSTREAM)
    out += d
    mf = struct.pack(f"<{len(mini_fat)}I", *mini_fat)
    out += mf + struct.pack("<I", FREESECT) * ((n_minifat * SECTOR - len(mf)) // 4)
    out += bytes(mini_stream) + b"\0" * (n_ministream * SECTOR - len(mini_stream))
    for n, count in zip(large, n_large, strict=True):
        out += n.data + b"\0" * (count * SECTOR - len(n.data))
    return bytes(out)


# ---------- MS-OVBA ----------


def ovba_compress(data: bytes) -> bytes:
    """A CompressedContainer of literal-only tokens: one flag byte (0x00) per 8 literal bytes.
    Every chunk but the last holds exactly 4096 bytes (stored raw, flag bit off); the last chunk
    is compressed-format with literals only (≤ 3640 bytes keeps it inside the 4098-byte cap)."""
    out = bytearray(b"\x01")
    rest = data
    while len(rest) > 3640:
        piece, rest = rest[:4096], rest[4096:]
        if len(piece) < 4096:  # can't be a raw chunk: fall through to the compressed path
            rest = piece + rest
            break
        out += struct.pack("<H", 0x3000 | (4096 + 2 - 3))  # raw chunk, size field = 4095
        out += piece
    tokens = bytearray()
    for i in range(0, len(rest), 8):
        tokens.append(0)
        tokens += rest[i : i + 8]
    assert len(tokens) <= 4096, "the last chunk is too long for a literal-only fixture"
    out += struct.pack("<H", 0xB000 | (len(tokens) + 2 - 3))
    out += tokens
    return bytes(out)


def _rec(rid: int, data: bytes) -> bytes:
    return struct.pack("<HI", rid, len(data)) + data


def vba_project(modules: dict[str, str], project: str = "VBAProject") -> bytes:
    """A vbaProject.bin with standard (procedural) modules, name → VBA source."""
    d = bytearray()
    d += _rec(0x0001, struct.pack("<I", 1))  # SYSKIND win32
    d += _rec(0x0002, struct.pack("<I", 0x409))  # LCID
    d += _rec(0x0014, struct.pack("<I", 0x409))  # LCIDINVOKE
    d += _rec(0x0003, struct.pack("<H", 1252))  # CODEPAGE
    d += _rec(0x0004, project.encode())  # NAME
    d += _rec(0x0005, b"") + _rec(0x0040, b"")  # DOCSTRING (+ unicode)
    d += _rec(0x0006, b"") + _rec(0x003D, b"")  # HELPFILEPATH 1 and 2
    d += _rec(0x0007, struct.pack("<I", 0))  # HELPCONTEXT
    d += _rec(0x0008, struct.pack("<I", 0))  # LIBFLAGS
    d += struct.pack("<HIIH", 0x0009, 4, 1, 0)  # VERSION (reserved=4, major, minor)
    d += _rec(0x000C, b"") + _rec(0x003C, b"")  # CONSTANTS (+ unicode)
    d += _rec(0x000F, struct.pack("<H", len(modules)))  # MODULES count
    d += _rec(0x0013, struct.pack("<H", 0xFFFF))  # PROJECTCOOKIE
    streams: dict[str, bytes] = {}
    project_text = 'ID="{00000000-0000-0000-0000-000000000000}"\r\n'
    for name in modules:
        b = name.encode()
        d += _rec(0x0019, b)  # MODULENAME
        d += _rec(0x0047, name.encode("utf-16-le"))  # MODULENAMEUNICODE
        d += _rec(0x001A, b) + _rec(0x0032, name.encode("utf-16-le"))  # STREAMNAME
        d += _rec(0x001C, b"") + _rec(0x0048, b"")  # DOCSTRING
        d += _rec(0x0031, struct.pack("<I", 0))  # MODULEOFFSET: source starts at 0
        d += _rec(0x001E, struct.pack("<I", 0))  # HELPCONTEXT
        d += _rec(0x002C, struct.pack("<H", 0xFFFF))  # COOKIE
        d += _rec(0x0021, b"")  # TYPE: procedural
        d += _rec(0x002B, b"")  # TERMINATOR
        source = f'Attribute VB_Name = "{name}"\r\n' + modules[name].replace("\n", "\r\n")
        while len(source.encode("cp1252")) % 4096 > 3640:  # see ovba_compress: keep the last
            source += "'\r\n"  # chunk short enough for literal tokens (a blank comment line)
        streams[f"VBA/{name}"] = ovba_compress(source.encode("cp1252"))
        project_text += f"Module={name}\r\n"
    d += _rec(0x0010, b"")  # dir TERMINATOR
    streams["VBA/dir"] = ovba_compress(bytes(d))
    streams["VBA/_VBA_PROJECT"] = bytes([0xCC, 0x61, 0xFF, 0xFF, 0x00, 0x00, 0x00])
    streams["PROJECT"] = (project_text + f'Name="{project}"\r\n').encode("cp1252")
    return build_ole(streams)
