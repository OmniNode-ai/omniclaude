from omnimarket.nodes.node_real.handlers.handler_real import HandlerReal


def bypass() -> None:
    # gh pr list --repo OmniNode-ai/omniclaude
    gh = "gh pr list --repo OmniNode-ai/omniclaude"
    print(HandlerReal, gh)
