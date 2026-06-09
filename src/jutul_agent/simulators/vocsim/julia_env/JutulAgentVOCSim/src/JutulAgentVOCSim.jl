module JutulAgentVOCSim

# Per-simulator warm-up package for VOCSim (placeholder). VOCSim.jl is not yet
# released, so there is no solve to bake; this still loads GLMakie under
# @recompile_invalidations so generic Jutul + Makie code is recompiled GLMakie-aware.
# Populate `_warm_solve` (and add a @compile_workload) once VOCSim ships.

using Jutul
using PrecompileTools: @recompile_invalidations

@recompile_invalidations begin
    using GLMakie
end

_warm_solve() = nothing

end # module
