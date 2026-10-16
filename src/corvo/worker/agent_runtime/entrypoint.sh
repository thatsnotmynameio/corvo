#!/bin/sh
# The agent worker's entrypoint (KTD13). It runs as root, with the container's
# cgroup writable, only long enough to hand uid 1000 the subtree its sessions'
# cgroups go in; then it runs its arguments as uid 1000, with no capability
# and no way to gain one.
set -eu

cgroup=/sys/fs/cgroup

# cgroup v2 enables controllers for children only in a cgroup with no process
# of its own, so the container's processes move to a leaf first.
mkdir "$cgroup/init"
for pid in $(cat "$cgroup/cgroup.procs"); do
    # A process that has exited since the read cannot move.
    echo "$pid" >"$cgroup/init/cgroup.procs" 2>/dev/null || true
done
echo "+cpu +memory +pids" >"$cgroup/cgroup.subtree_control"

# uid 1000 gets the directory and the three files it needs to make a cgroup
# for each run and move a session into it, and none of agents/ own limits.
mkdir "$cgroup/agents"
chown 1000:1000 "$cgroup/agents" "$cgroup/agents/cgroup.procs" \
    "$cgroup/agents/cgroup.threads" "$cgroup/agents/cgroup.subtree_control"
mkdir "$cgroup/agents/worker"
echo $$ >"$cgroup/agents/worker/cgroup.procs"

exec setpriv --reuid=1000 --regid=1000 --clear-groups --no-new-privs \
    --inh-caps=-all --bounding-set=-all -- "$@"
