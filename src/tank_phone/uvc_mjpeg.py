#!/usr/bin/env python3
"""uvc_mjpeg.py — stdlib-only UVC MJPEG producer for the tank phone GUI.

Grabs Motion-JPEG frames from a V4L2 camera (e.g. /dev/video0) via MMAP and
writes concatenated JPEGs to stdout — the same byte stream `rpicam-vid
--codec mjpeg -o -` produces, so tank_phone/server.py relays it unchanged.

    python3 uvc_mjpeg.py --frames 1 --out /tmp/still.jpg   # one still (test)
    python3 uvc_mjpeg.py                                    # stream to stdout

As the phone server source:
    TANK_PHONE_MJPEG_CMD="python3 $HOME/tank_phone/uvc_mjpeg.py"

Stdlib only (fcntl, mmap, struct). No motors, no servos, no bus writes —
camera capture only.
"""

import argparse
import fcntl
import mmap
import os
import struct
import sys

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0


def _fourcc(a, b, c, d):
    return ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


def _iowr(nr, size):
    return (2 | 1) << 30 | (size << 16) | (0x56 << 8) | nr


def _iow(nr, size):
    return 1 << 30 | (size << 16) | (0x56 << 8) | nr


VIDIOC_S_FMT = _iowr(5, 208)
VIDIOC_REQBUFS = _iowr(8, 20)
VIDIOC_QUERYBUF = _iowr(9, 88)
VIDIOC_QBUF = _iowr(15, 88)
VIDIOC_DQBUF = _iowr(17, 88)
VIDIOC_STREAMON = _iow(18, 4)
VIDIOC_STREAMOFF = _iow(19, 4)

assert struct.calcsize("<5I16s16s2I4xI4x3I4x") == 88, "v4l2_buffer layout"
assert struct.calcsize("<I12I156s") == 208, "v4l2_format layout"


def _buf(itype=1, memory=1, index=0, offset=0, length=0):
    return struct.pack("<5I16s16s2I4xI4x3I4x",
                       index, itype, 0, 0, 0, b"\0" * 16, b"\0" * 16,
                       0, memory, offset, length, 0, 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--frames", type=int, default=0, help="0 = forever")
    ap.add_argument("--out", default="", help="write stills here, not stdout")
    args = ap.parse_args(argv)

    fd = os.open(args.device, os.O_RDWR)  # blocking: DQBUF waits for a frame
    fmt = struct.pack("<12I", args.width, args.height,
                      _fourcc("M", "J", "P", "G"), V4L2_FIELD_ANY,
                      0, 0, 0, 0, 0, 0, 0, 0) + b"\0" * 156
    fcntl.ioctl(fd, VIDIOC_S_FMT,
                bytearray(struct.pack("<I", 1) + fmt))
    req = struct.pack("<4I4B", 4, 1, 1, 0, 0, 0, 0, 0)
    count = struct.unpack("<I", fcntl.ioctl(fd, VIDIOC_REQBUFS, req)[:4])[0]
    if count < 2:
        sys.exit("REQBUFS gave %d buffers" % count)

    maps, geom = [], []
    for i in range(count):
        q = fcntl.ioctl(fd, VIDIOC_QUERYBUF, _buf(index=i))
        offset = struct.unpack("<I", q[64:68])[0]
        length = struct.unpack("<I", q[72:76])[0]
        maps.append(mmap.mmap(fd, length, offset=offset))
        geom.append((offset, length))
        fcntl.ioctl(fd, VIDIOC_QBUF,
                    _buf(index=i, offset=offset, length=length))
    fcntl.ioctl(fd, VIDIOC_STREAMON, struct.pack("<i", 1))

    out = open(args.out, "wb") if args.out else sys.stdout.buffer
    try:
        n = 0
        while args.frames <= 0 or n < args.frames:
            d = fcntl.ioctl(fd, VIDIOC_DQBUF, _buf())
            index = struct.unpack("<I", d[0:4])[0]
            used = struct.unpack("<I", d[8:12])[0]
            out.write(maps[index][:used])
            out.flush()
            off, ln = geom[index]
            fcntl.ioctl(fd, VIDIOC_QBUF,
                        _buf(index=index, offset=off, length=ln))
            n += 1
            if args.out and args.frames == 1:
                break
    finally:
        try:
            fcntl.ioctl(fd, VIDIOC_STREAMOFF, struct.pack("<i", 1))
        except OSError:
            pass
        for m in maps:
            m.close()
        os.close(fd)
        if args.out:
            out.close()


if __name__ == "__main__":
    main()
