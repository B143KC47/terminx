PALETTE = [
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_blue",
    "bright_red",
    "orange1",
    "spring_green1",
    "deep_sky_blue1",
    "hot_pink",
    "yellow3",
    "violet",
]


def auto_color(agent: str) -> str:
    return PALETTE[sum(ord(ch) for ch in agent) % len(PALETTE)]


def agent_color(agent: str, state_colors: dict, cfg_colors: dict) -> str:
    if agent in state_colors and state_colors[agent]:
        return state_colors[agent]
    if agent in cfg_colors and cfg_colors[agent]:
        return cfg_colors[agent]
    return auto_color(agent)


def cycle_color(agent: str, state_colors: dict, cfg_colors: dict) -> str:
    current = agent_color(agent, state_colors, cfg_colors)
    try:
        idx = PALETTE.index(current)
    except ValueError:
        idx = -1
    return PALETTE[(idx + 1) % len(PALETTE)]
