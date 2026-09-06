import os
import socket
import sys

import uvicorn

# Unbuffered stdout, or the access log below is written and then LOST.
#
# Python block-buffers stdout when it is redirected to a file rather than a
# terminal, and a dev server is normally ended by killing it -- at which point
# the buffer is never flushed. Measured: a redirected process that printed a
# line three seconds before being killed produced a ZERO-BYTE file. Every server
# log captured while building this feature was empty for exactly that reason,
# including the ones meant to be the record for the open Dependency Graph crash.
#
# So the comment below was true about configuration and false about outcome:
# access logging was on, and nothing was ever readable. Reconfiguring stdout is
# what makes the rest of this comment mean something.
sys.stdout.reconfigure(line_buffering=True)

# Access logging is ON (uvicorn's default) and deliberately not suppressed.
#
# It already records the query string, which is where the UI's filter state
# lives -- segments, languages, subsystem, q, hideNoise, hideZeroFanIn, view.
# Verified in uvicorn's own source rather than assumed: AccessFormatter builds
# `request_line` from `get_path_with_query_string(scope)`, which appends
# `?<query_string>` when one is present. An earlier attempt to "add" this by
# overriding the access formatter produced a byte-identical format string -- a
# no-op that would have read like a fix.
#
# So: do not pass access_log=False or --no-access-log for quiet. The log is the
# record for the open Dependency Graph crash (reported once, boundary-caught,
# never reproduced, triggered by a filter interaction) and the next occurrence
# should be diagnosable from it rather than from another reproduction hunt.
# THE PORT GUARD. Moved here from app/main.py on 2026-09-04; see the note there
# for why, and do not move it back.
#
# WHAT IT CATCHES, which is real and was found live during Phase H1.5: two
# independent `uvicorn --reload` processes left running from different points in
# one long session produced several minutes of requests that appeared to hang
# with no error anywhere, because each landed on whichever process's worker
# happened to still be alive and busy.
#
# WHY *HERE* AND NOWHERE ELSE. This is the parent, and it runs BEFORE
# `uvicorn.run` binds anything -- so the probe answers the question actually
# being asked ("is some OTHER server already on this port") rather than the
# question a worker-side probe is forced to answer ("is anything on this port",
# to which its own reloader parent is always the answer).
#
# NOT special-cased on reload, and NOT detecting the parent via getppid or any
# uvicorn internal. Both were considered and rejected: a guard whose correctness
# depends on undocumented process topology is a fragile instrument protecting
# against a fragile failure, and this project has enough recorded instances of
# the instrument being the thing that broke. Running once, in the right process,
# needs no cleverness and no exclusions.
def _fail_loudly_if_port_already_bound(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(
                f"127.0.0.1:{port} is already answering -- another backend instance is "
                "still running (or never fully stopped). Kill it before starting a new "
                "one; two overlapping dev servers silently share the port and requests "
                "hang unpredictably instead of failing clearly."
            )


PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    # Once, in the parent, before anything binds.
    _fail_loudly_if_port_already_bound(PORT)
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=True)
