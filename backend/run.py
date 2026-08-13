import uvicorn

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
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
