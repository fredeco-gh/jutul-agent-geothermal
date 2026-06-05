# Ensemble helpers for jutul-agent: warm Distributed workers + pmap, for the
# parallel runs an uncertainty quantification or parameter sweep needs. Loaded into
# the session on demand (like julia_plot.jl), so it adds no environment dependency.
#
# Design: the agent's eval runs in the *master* process, so `addprocs` + `pmap`
# here are the standard Julia pattern — the master has every package loaded, so the
# "packages must be on the master" class of failure (the old worker-based backend's
# pain) cannot occur. Workers inherit the master's project and system image, so they
# boot warm.

module JutulAgentEnsemble

using Distributed

export run_ensemble, warm_addprocs

"""
    warm_addprocs(n; threads=nothing) -> Vector{Int}

Add `n` worker processes that inherit this (master) process's project and system
image, so they start warm — no second precompile. Returns the new worker ids.
"""
function warm_addprocs(n::Integer; threads::Union{Nothing,Integer}=nothing)
    n <= 0 && return Int[]
    flags = String[]
    proj = Base.active_project()
    proj === nothing || push!(flags, "--project=$(dirname(proj))")
    # Forward a *custom* system image so workers skip a cold precompile; the default
    # system image (under the Julia install) is found automatically, so leave it off.
    img = unsafe_string(Base.JLOptions().image_file)
    if !isempty(img) && isfile(img) && !startswith(img, Sys.BINDIR)
        push!(flags, "--sysimage=$img")
    end
    threads === nothing || push!(flags, "--threads=$(threads)")
    return addprocs(Int(n); exeflags=`$flags`)
end

"""
    run_ensemble(f, cases; nworkers=length(cases), setup=nothing,
                 threads=nothing, keep_workers=false) -> Vector

Run `f(case)` for each `case` in `cases` in parallel across warm workers and return
the results in order. Spawns workers as needed (up to `nworkers`, capped at the
number of cases), optionally evaluates `setup` (an expression, e.g.
`:(using JutulDarcy)`) on every worker first, `pmap`s the work, then removes the
workers it spawned unless `keep_workers`.

`f` runs on the workers, so anything it needs must be available there: load packages
via `setup`, and prefer a named top-level function over a closure capturing local
state.
"""
function run_ensemble(
    f,
    cases;
    nworkers::Integer=length(cases),
    setup::Union{Nothing,Expr}=nothing,
    threads::Union{Nothing,Integer}=nothing,
    keep_workers::Bool=false,
)
    cases = collect(cases)
    isempty(cases) && return Any[]
    existing = filter(!=(1), Distributed.workers())  # workers() is [1] when none
    target = min(Int(nworkers), length(cases))
    spawned = length(existing) < target ? warm_addprocs(target - length(existing); threads) : Int[]
    try
        setup === nothing || Distributed.remotecall_eval(Main, Distributed.workers(), setup)
        return pmap(f, cases)
    finally
        (keep_workers || isempty(spawned)) || rmprocs(spawned)
    end
end

end # module
