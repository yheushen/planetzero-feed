"""A small GRIB2 reader, standard library only, for the wind Earth draws (session 7, part 69): NOAA GFS's 10 m wind from NOMADS.

GFS's files pack their numbers with "complex packing and spatial differencing" (data template 5.3), which nothing in the standard
library reads. Written from the WMO's GRIB2 tables (section 5 template 5.3, section 7 template 7.3) and NCEP's g2clib (comunpack.c);
the feed_earth suite (F25) holds it to the values ecCodes, ECMWF's reader, gives for the same file. It reads what GFS sends: a
regular latitude and longitude grid (grid template 3.0), product template 4.0, data templates 5.0, 5.2 and 5.3, with or without
a bitmap. Anything else raises GribError, so a change at NOAA shows as a missing layer, never as wrong numbers (invariant 10).
"""
import math
import struct


class GribError(Exception):
    """The file is not what this reader knows how to read."""


def _u(b, i, n):
    return int.from_bytes(b[i:i + n], "big")


def _s(b, i, n):
    """A signed number GRIB's way: the first bit is the sign, the rest the size (not two's complement)."""
    v = _u(b, i, n)
    top = 1 << (8 * n - 1)
    return -(v - top) if v & top else v


class _Bits:
    """Unsigned numbers of any width, read one after another from a run of bytes, most significant bit first."""

    def __init__(self, data, pos=0):
        self.data, self.pos = data, pos

    def take(self, width):
        if width == 0:
            return 0
        start, end = self.pos >> 3, (self.pos + width + 7) >> 3
        chunk = int.from_bytes(self.data[start:end], "big")
        shift = (end - start) * 8 - (self.pos & 7) - width
        self.pos += width
        return (chunk >> shift) & ((1 << width) - 1)

    def many(self, n, width):
        return [self.take(width) for _ in range(n)]

    def align(self):
        self.pos = (self.pos + 7) & ~7


def _sections(msg):
    """{section number: its bytes} for 1 message; sections 2 to 7 may repeat in GRIB2, which GFS's files never do."""
    out, i = {}, 16
    while i < len(msg) - 4:
        length, num = _u(msg, i, 4), msg[i + 4]
        if length < 5:
            raise GribError(f"a section of length {length}")
        out[num] = msg[i:i + length]
        i += length
    if msg[-4:] != b"7777":
        raise GribError("the message does not end with 7777")
    return out


def _grid(s3):
    tmpl = _u(s3, 12, 2)
    if tmpl != 0:
        raise GribError(f"grid template 3.{tmpl}; only 3.0 (latitude and longitude) is read")
    ni, nj = _u(s3, 30, 4), _u(s3, 34, 4)
    basic, sub = _u(s3, 38, 4), _u(s3, 42, 4)
    unit = 1e-6 if basic in (0, 0xFFFFFFFF) or sub in (0, 0xFFFFFFFF) else basic / sub
    la1, lo1 = _s(s3, 46, 4) * unit, _s(s3, 50, 4) * unit
    la2, lo2 = _s(s3, 55, 4) * unit, _s(s3, 59, 4) * unit
    di, dj = _u(s3, 63, 4) * unit, _u(s3, 67, 4) * unit
    scan = s3[71]
    if scan & 0b11110000 not in (0, 0b01000000) or scan & 0b00100000:
        raise GribError(f"scanning mode {scan:08b}: only rows west to east, one after another, are read")
    return {"ni": ni, "nj": nj, "la1": la1, "lo1": lo1, "la2": la2, "lo2": lo2, "di": di, "dj": dj, "north_first": not (scan & 0b01000000)}


def _product(s4):
    tmpl = _u(s4, 7, 2)
    if tmpl != 0:
        raise GribError(f"product template 4.{tmpl}; only 4.0 is read")
    units = {0: 1 / 60, 1: 1, 2: 24, 10: 3, 11: 6, 12: 12, 13: 1 / 3600}
    unit = s4[17]
    if unit not in units:
        raise GribError(f"forecast time unit {unit}")
    scale, value = _s(s4, 23, 1), _s(s4, 24, 4)
    return {"category": s4[9], "number": s4[10], "hours": _u(s4, 18, 4) * units[unit], "surface": s4[22],
            "level": value / (10 ** scale) if scale else value}


def _unpack(s5, s7, npacked):
    tmpl = _u(s5, 9, 2)
    ref = struct.unpack(">f", s5[11:15])[0]
    e, d, nbits = _s(s5, 15, 2), _s(s5, 17, 2), s5[19]
    two_e, ten_d = 2.0 ** e, 10.0 ** -d
    data = s7[5:]
    if tmpl == 0:
        bits = _Bits(data)
        return [(ref + bits.take(nbits) * two_e) * ten_d for _ in range(npacked)]
    if tmpl not in (2, 3):
        raise GribError(f"data template 5.{tmpl}; only 5.0, 5.2 and 5.3 are read")
    missing = s5[22]
    if missing != 0:
        raise GribError(f"missing value management {missing}; GFS's wind has none")
    ng = _u(s5, 31, 4)
    width_ref, width_bits = s5[35], s5[36]
    len_ref, len_inc, len_last, len_bits = _u(s5, 37, 4), s5[41], _u(s5, 42, 4), s5[46]
    order = ndesc = 0
    bits = _Bits(data)
    if tmpl == 3:
        order, ndesc = s5[47], s5[48]
        if order not in (1, 2):
            raise GribError(f"spatial differencing of order {order}")
        firsts = [_s(data, i * ndesc, ndesc) for i in range(order)]
        minsd = _s(data, order * ndesc, ndesc)
        bits.pos = (order + 1) * ndesc * 8
    refs = bits.many(ng, nbits)
    bits.align()
    widths = [width_ref + w for w in bits.many(ng, width_bits)]
    bits.align()
    lengths = [len_ref + x * len_inc for x in bits.many(ng, len_bits)]
    bits.align()
    if ng:
        lengths[-1] = len_last
    if sum(lengths) != npacked:
        raise GribError(f"the groups hold {sum(lengths)} numbers, the section says {npacked}")
    ints = []
    for r, w, n in zip(refs, widths, lengths):
        if w == 0:
            ints.extend([r] * n)
        else:
            ints.extend(r + bits.take(w) for _ in range(n))
    if tmpl == 3:
        if order == 1:
            ints[0] = firsts[0]
            for k in range(1, len(ints)):
                ints[k] = ints[k] + minsd + ints[k - 1]
        else:
            ints[0], ints[1] = firsts
            for k in range(2, len(ints)):
                ints[k] = ints[k] + minsd + 2 * ints[k - 1] - ints[k - 2]
    return [(ref + v * two_e) * ten_d for v in ints]


def messages(blob):
    """Every message in a GRIB2 file: [{"grid", "product", "values"}], values in rows south to north, each row west to east,
    None where a bitmap says there is no value."""
    out, i = [], 0
    while i < len(blob):
        if blob[i:i + 4] != b"GRIB":
            raise GribError(f"no GRIB message at byte {i}")
        if blob[i + 7] != 2:
            raise GribError(f"GRIB edition {blob[i + 7]}; only 2 is read")
        total = _u(blob, i + 8, 8)
        msg = blob[i:i + total]
        s = _sections(msg)
        for need in (3, 4, 5, 7):
            if need not in s:
                raise GribError(f"no section {need}")
        g, p = _grid(s[3]), _product(s[4])
        npoints = _u(s[3], 6, 4)
        npacked = _u(s[5], 5, 4)
        vals = _unpack(s[5], s[7], npacked)
        if 6 in s and s[6][5] == 0:
            bitmap = _Bits(s[6][6:])
            it = iter(vals)
            vals = [next(it) if bitmap.take(1) else None for _ in range(npoints)]
        elif len(vals) != npoints:
            raise GribError(f"{len(vals)} numbers for {npoints} points and no bitmap")
        if g["north_first"]:   # GFS writes north to south: turn it into south to north, as grid.json's rows are
            vals = [v for r in range(g["nj"] - 1, -1, -1) for v in vals[r * g["ni"]:(r + 1) * g["ni"]]]
        g["lat0"] = min(g["la1"], g["la2"])
        out.append({"grid": g, "product": p, "values": vals})
        i += total
    return out


def wind_10m(blob):
    """GFS's 10 m wind in a file holding UGRD and VGRD at 10 m above the ground: (grid, u m/s, v m/s, forecast hours)."""
    u = v = None
    for m in messages(blob):
        p = m["product"]
        if p["category"] != 2 or p["surface"] != 103 or not math.isclose(p["level"], 10):
            continue
        if p["number"] == 2:
            u = m
        elif p["number"] == 3:
            v = m
    if u is None or v is None:
        raise GribError("no 10 m wind (UGRD and VGRD) in the file")
    if u["grid"] != v["grid"]:
        raise GribError("UGRD and VGRD on different grids")
    return u["grid"], u["values"], v["values"], u["product"]["hours"]
