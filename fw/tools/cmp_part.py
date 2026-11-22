import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""比较自编译 partitions.bin 与设备备份里 0x8000 处的分区表，并打印解析结果。"""
import io
import os
import struct

FW = _FW
BACKUP = _os.environ.get("MOCHI_BACKUP", _os.path.join(_ROOT, "_work", "flash_backup_original.bin"))
BUILT = os.path.join(FW, ".pio", "build", "clawdmochi", "partitions.bin")

stock = open(BACKUP, "rb").read()[0x8000:0x8000 + 0xC00]
built = open(BUILT, "rb").read()

print("built partitions.bin size:", len(built))
print("stock slice size:", len(stock))
n = min(len(stock), len(built))
same = stock[:n] == built[:n]
print("first %d bytes identical:" % n, same)
if not same:
    for i in range(n):
        if stock[i] != built[i]:
            print("first diff at offset 0x%X: stock=%02X built=%02X" % (i, stock[i], built[i]))
            break

MAGIC = 0x50AA


def parse(buf, label):
    print("\n== %s ==" % label)
    esps = []
    off = 0
    while off + 32 <= len(buf):
        magic, ptype, subtype, offset, size, namelen = struct.unpack_from("<HBBIIB", buf, off)
        if magic != MAGIC:
            break
        name = buf[off + 12:off + 12 + namelen].decode("utf-8", "replace")
        esps.append((name, ptype, subtype, offset, size))
        print("  %-10s type=%d subtype=0x%02X offset=0x%06X size=0x%06X (%d KB)"
              % (name, ptype, subtype, offset, size, size // 1024))
        off += 32
    return esps


a = parse(stock, "stock (flash backup @0x8000)")
b = parse(built, "built partitions.bin")
print("\ntable equal:", a == b)
print("entry count:", len(a), len(b))
