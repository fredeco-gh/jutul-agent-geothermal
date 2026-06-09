module JutulAgentBattMo

# Per-simulator warm-up package for BattMo. Bakes the agent's solve path (the shipped
# chen_2020 cell with a constant-current discharge, mirroring the battmo-overview
# skill). See JutulAgentJutulDarcy for the @recompile_invalidations rationale.

using BattMo, Jutul
using PrecompileTools: @recompile_invalidations, @setup_workload, @compile_workload

@recompile_invalidations begin
    using GLMakie
end

function _warm_solve()
    cell = load_cell_parameters(; from_default_set = "chen_2020")
    protocol = load_cycling_protocol(; from_default_set = "cc_discharge")
    sim = Simulation(LithiumIonBattery(), cell, protocol)
    solve(sim; info_level = -1)
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
