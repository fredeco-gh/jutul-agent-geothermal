# Julia kernel server (standard library only). Shipped as a resource and run as
#   julia [flags] server.jl <control_port>      with env JK_TOKEN set
#
# Channels (this is the whole protocol):
#   * control — a loopback TCP socket this process connects back to. Carries the
#     READY handshake and exactly one framed result per eval: "OK\t<b64 repr>",
#     "ERR\t<b64 showerror>", or "INT". User output never crosses it, so errors
#     are authoritative (the parent never sniffs stdout for them).
#   * stdout / stderr — the inherited pipes the parent owns; user output streams
#     live. After every eval a unique SENTINEL is written to both so the parent
#     knows each eval's output extent.
#
# Interrupt: SIGINT raises InterruptException in the running eval; the result
# bookkeeping (sentinels + frame) runs under disable_sigint so a late signal
# can't corrupt the wire.

using Sockets, Base64

const SENTINEL = "\x1e\x1eJK-EVAL-DONE\x1e\x1e\n"

# Render an error like the REPL: the message, then a backtrace whose giant
# specialized type signatures are depth-limited to `{…}`. A deeply specialized
# frame's argument types can otherwise print to tens of kilobytes;
# `:stacktrace_types_limited` is the same IOContext key the REPL uses, so this
# reuses Julia's own machinery.
function format_error(e, bt)
    try
        frames = Base.stacktrace(bt)
        # Drop the server/boot plumbing below the user's top-level eval (`none`).
        cut = findfirst(sf -> sf.file === Symbol("none"), frames)
        cut !== nothing && (frames = frames[1:cut])
        return sprint(Base.showerror, e, frames;
                      context = (:stacktrace_types_limited => Ref(false),
                                 :limit => true, :displaysize => (40, 120)))
    catch
        # Error formatting must never break the eval loop; fall back to the message.
        return try
            sprint(showerror, e)
        catch
            string(typeof(e), " (could not be displayed)")
        end
    end
end

# Byte cap on any payload, bounding a pathologically long error message or value
# repr. Compact formatting keeps normal errors well under this, so it rarely fires.
const PAYLOAD_CAP = 65_536

function cap_payload(s::AbstractString)
    sizeof(s) <= PAYLOAD_CAP && return s
    # Truncate at a valid character boundary at or before the byte cap.
    idx = thisind(s, min(PAYLOAD_CAP, lastindex(s)))
    return string(SubString(s, firstindex(s), idx),
                  "\n… (output truncated; ", sizeof(s) - idx, " more bytes)")
end

Base.exit_on_sigint(false)   # SIGINT -> InterruptException instead of process exit

"REPL-style text/plain repr; \"\" for nothing so the parent can omit it."
function value_repr(val)
    val === nothing && return ""
    # `invokelatest` so a `show` method defined later in the session (a newer world
    # age than this function) is honoured instead of a stale default repr.
    try
        return sprint(io -> Base.invokelatest(show,
            IOContext(io, :limit => true, :compact => false), MIME("text/plain"), val))
    catch
    end
    try
        return Base.invokelatest(string, val)
    catch
    end
    # Neither show nor string worked (e.g. an object with no text form). The type
    # is always printable and tells the caller what it got.
    return try
        string("<", typeof(val), ": value cannot be displayed as text>")
    catch
        "<value cannot be displayed as text>"
    end
end

function emit_result(ctrl, tag, payload)
    # Atomic w.r.t. interrupts: close the eval's output then send its one frame.
    Base.disable_sigint() do
        flush(stdout); flush(stderr)
        print(stdout, SENTINEL); flush(stdout)
        print(stderr, SENTINEL); flush(stderr)
        frame = tag == "INT" ? "INT\n" : string(tag, "\t", base64encode(payload), "\n")
        write(ctrl, frame); flush(ctrl)
    end
end

# Julia binds a script's top-level `include` to that script's directory, so a
# user's `include("foo.jl")` would look next to this server file rather than the
# working directory (the workspace, where files are written). Rewrite top-level
# `include(x)` to `include(abspath(x))` — the cwd is the workspace — so relative
# paths resolve there. Absolute paths and nested includes are unaffected.
function rewrite_includes!(ex)
    ex isa Expr || return ex
    if ex.head === :call && length(ex.args) == 2 && ex.args[1] === :include
        ex.args[2] = Expr(:call, :abspath, ex.args[2])
    else
        foreach(rewrite_includes!, ex.args)
    end
    return ex
end

function main()
    port = parse(Int, ARGS[1])
    token = get(ENV, "JK_TOKEN", "")
    ctrl = connect(ip"127.0.0.1", port)

    # Handshake, then a SENTINEL on each stream so any startup/precompile preamble
    # is bounded as "segment 0" and the first eval starts clean.
    write(ctrl, string("READY\t", token, "\n")); flush(ctrl)
    flush(stdout); flush(stderr)
    print(stdout, SENTINEL); flush(stdout)
    print(stderr, SENTINEL); flush(stderr)

    while true
        local line
        try
            line = readline(ctrl)
        catch e
            e isa InterruptException && continue   # stray interrupt between evals
            rethrow()
        end
        if line == ""
            eof(ctrl) && break                     # parent closed the control socket
            continue
        end

        code = String(base64decode(line))
        tag = "OK"
        payload = ""
        try
            val = Core.eval(Main, rewrite_includes!(Meta.parseall(code)))  # output streams to fd1/fd2
            payload = value_repr(val)
        catch e
            if e isa InterruptException
                tag = "INT"
            else
                tag = "ERR"
                payload = format_error(e, catch_backtrace())
            end
        end
        emit_result(ctrl, tag, cap_payload(payload))
    end
end

main()
