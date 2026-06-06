"""Training entrypoint placeholder for the hybrid state encoder."""

from __future__ import annotations

import typer

from services.ml.encoders.hybrid_encoder import HybridStateEncoder

app = typer.Typer(no_args_is_help=False)


@app.command()
def main(temporal_features: int = 20, static_features: int = 10) -> None:
    """Instantiate the encoder so pipeline wiring can validate dimensions."""
    encoder = HybridStateEncoder(
        temporal_features=temporal_features,
        static_features=static_features,
    )
    typer.echo(f"hybrid_encoder_ready state_size={encoder.config.state_size}")


if __name__ == "__main__":
    app()
