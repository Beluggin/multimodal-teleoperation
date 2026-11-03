/* qstream.c — minimal V4L2 MJPEG capture for the tank's USB camera.
 *
 * The Python packer (uvc_mjpeg.py) hits a QBUF EINVAL ghost on this Pi;
 * this C twin of the same ioctls works. Build on the Pi:
 *   gcc -O2 -o /tmp/qstream qstream.c
 * One frame:   /tmp/qstream 1 > frame.jpg
 * Stream:      /tmp/qstream 0 > stream.mjpg   (0 = forever; phone server
 *               consumes this via TANK_PHONE_MJPEG_CMD=/tmp/qstream)
 * Capture only — no motors, no servos, no bus writes.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/videodev2.h>

static int xioctl(int fd, unsigned long req, void *arg) {
    int r;
    do { r = ioctl(fd, req, arg); } while (r < 0 && errno == EINTR);
    return r;
}

int main(int argc, char **argv) {
    long want = argc > 1 ? atol(argv[1]) : 0; /* 0 = forever */
    const char *dev = argc > 2 ? argv[2] : "/dev/video0";
    int fd = open(dev, O_RDWR);
    if (fd < 0) { perror("open"); return 1; }

    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof fmt);
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = 640;
    fmt.fmt.pix.height = 480;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
    fmt.fmt.pix.field = V4L2_FIELD_ANY;
    if (xioctl(fd, VIDIOC_S_FMT, &fmt) < 0) { perror("S_FMT"); return 1; }

    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof req);
    req.count = 4;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd, VIDIOC_REQBUFS, &req) < 0 || req.count < 2) {
        perror("REQBUFS"); return 1;
    }

    void *maps[32];
    size_t lens[32];
    for (unsigned i = 0; i < req.count; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof buf);
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (xioctl(fd, VIDIOC_QUERYBUF, &buf) < 0) { perror("QUERYBUF"); return 1; }
        maps[i] = mmap(NULL, buf.length, PROT_READ | PROT_WRITE,
                       MAP_SHARED, fd, buf.m.offset);
        if (maps[i] == MAP_FAILED) { perror("mmap"); return 1; }
        lens[i] = buf.length;
        if (xioctl(fd, VIDIOC_QBUF, &buf) < 0) { perror("QBUF"); return 1; }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) { perror("STREAMON"); return 1; }

    long got = 0;
    while (want <= 0 || got < want) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof buf);
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        if (xioctl(fd, VIDIOC_DQBUF, &buf) < 0) { perror("DQBUF"); return 1; }
        fwrite(maps[buf.index], buf.bytesused, 1, stdout);
        fflush(stdout);
        got++;
        if (xioctl(fd, VIDIOC_QBUF, &buf) < 0) { perror("QBUF"); return 1; }
    }
    (void)lens;
    return 0;
}
