def render_metrics(*, ready: bool) -> str:
    value = 1 if ready else 0
    return (
        "# HELP gen3d_ready Whether the gen3d service is ready.\n"
        "# TYPE gen3d_ready gauge\n"
        f"gen3d_ready {value}\n"
    )
