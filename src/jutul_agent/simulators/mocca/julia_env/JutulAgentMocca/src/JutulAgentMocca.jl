module JutulAgentMocca

# Per-simulator warm-up package for Mocca, which ships no PrecompileTools workload.
# Bakes the agent's simulate_process + plot_outlet paths (the shipped DCB quick-start;
# one workload because plot_outlet needs the solve's states). See JutulAgentJutulDarcy
# for the @recompile_invalidations rationale.

using Mocca, Jutul
using PrecompileTools: @recompile_invalidations, @setup_workload, @compile_workload

@recompile_invalidations begin
    using GLMakie
end

function _warm_solve()
    json_dir = joinpath(dirname(pathof(Mocca)), "../models/json/")
    constants, info = Mocca.parse_input(joinpath(json_dir, "haghpanah_DCB_input_simple.json"))
    case, ts_config = Mocca.setup_mocca_case(constants, info)
    states, timesteps =
        Mocca.simulate_process(case; timestep_selector_cfg = ts_config, info_level = 0)
    Mocca.plot_outlet(case, states, timesteps)
    return nothing
end

@setup_workload begin
    @compile_workload begin
        try
            _warm_solve()
        catch
        end
    end
end

end # module
