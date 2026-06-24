# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import os
import time

from mirage import MountMode, Workspace
from mirage.resource.ssh import SSHConfig, SSHResource

# ~/.ssh/config:
#   Host dev
#       HostName ec2-18-224-181-224.us-east-2.compute.amazonaws.com
#       IdentityFile ~/.ssh/dev.pem
#       User ubuntu
#       Port 22

config = SSHConfig(
    host="dev",
    root="/home/ubuntu/mirage-test",
    known_hosts=None,
)
resource = SSHResource(config)

with Workspace(
    {"/ssh/": resource},
        mode=MountMode.WRITE,
        fuse_mounts={"/": True},
) as ws:
    time.sleep(1)
    mp = ws.fuse_mountpoints["/"]

    print(f"=== FUSE MODE: mounted at {mp} ===\n")

    print("--- os.listdir() top-level ---")
    top_level = os.listdir(f"{mp}/ssh")
    for entry in top_level:
        print(f"  {entry}")

    if not top_level:
        print("  no entries found")
    else:
        print(f"\n--- open() + read {top_level[0]} ---")
        path = f"{mp}/ssh/{top_level[0]}"
        if os.path.isfile(path):
            with open(path) as f:
                content = f.read().strip()
            for line in content.splitlines()[:5]:
                print(f"  {line[:120]}")
            if len(content.splitlines()) > 5:
                print(f"  ... ({len(content.splitlines())} lines total)")

        print("\n--- os.stat() ---")
        for entry in top_level:
            st = os.stat(f"{mp}/ssh/{entry}")
            kind = "dir" if os.path.isdir(f"{mp}/ssh/{entry}") else "file"
            print(f"  {entry}: {kind}, {st.st_size} bytes")

        print("\n--- os.walk() ---")
        for root, dirs, files in os.walk(f"{mp}/ssh"):
            rel = os.path.relpath(root, f"{mp}/ssh")
            for f in files:
                print(f"  {os.path.join(rel, f)}")

    print(f"\n>>> FUSE mounted at: {mp}")
    print(">>> Open another terminal and run:")
    print(f">>>   ls {mp}/ssh/")
    print(f">>>   cat {mp}/ssh/readme.txt")
    print(">>> Press Enter to unmount and exit...")
    input()

    records = ws.ops.records
    total = sum(r.bytes for r in records)
    print(f"\nStats: {len(records)} ops, "
          f"{total} bytes transferred")
