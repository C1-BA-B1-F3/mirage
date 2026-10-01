import os
import sys

fd = os.open(
    "/data/file",
    os.O_WRONLY | (os.O_APPEND if sys.argv[1] == "append" else os.O_TRUNC),
)
os.write(fd, b"first")
os.write(fd, b"+")
os.listdir("/other")
os.write(fd, b"second")
os.listdir("/other")
os.close(fd)
os.listdir("/other")
