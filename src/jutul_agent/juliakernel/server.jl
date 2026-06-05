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

Base.exit_on_sigint(false)   # SIGINT -> InterruptException instead of process exit

"REPL-style text/plain repr; \"\" for nothing so the parent can omit it."
function value_repr(val)
    val === nothing && return ""
    try
        return sprint(io -> show(IOContext(io, :limit => true, :compact => false),
                                 MIME("text/plain"), val))
    catch
        return try; string(val); catch; "<unprintable value>"; end
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
            val = Core.eval(Main, Meta.parseall(code))   # user output streams to fd1/fd2
            payload = value_repr(val)
        catch e
            if e isa InterruptException
                tag = "INT"
            else
                tag = "ERR"
                payload = sprint(showerror, e, catch_backtrace())
            end
        end
        emit_result(ctrl, tag, payload)
    end
end

main()
