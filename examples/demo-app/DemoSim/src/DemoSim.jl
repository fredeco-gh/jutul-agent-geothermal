module DemoSim

# A tiny stand-in "simulator" for the server example. It has no physics and no
# dependencies; its only job is to give the agent something to call and plot, so
# the example stays about the agent/server wiring rather than a real model.

export response

"""
    response(p; n = 200)

Return `(; x, y)` for a damped sinusoid whose frequency scales with `p`. Think of
`p` as the one knob a user might turn in the web app.
"""
function response(p::Real; n::Integer = 200)
    x = collect(range(0, 4π; length = n))
    y = @. exp(-0.15 * x) * sin(p * x)
    return (; x = x, y = y)
end

end # module
