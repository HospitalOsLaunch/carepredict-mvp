"""Runtime configuration for the FastAPI service.

Configures PyTorch global settings (threads, precision, determinism) to ensure
reproducible inference and predictable performance characteristics across
deployments. Called once at application startup via the lifespan handler.
"""

from __future__ import annotations

import os

import structlog
import torch

logger = structlog.get_logger(__name__)


def configure_torch_runtime() -> None:
    """Configure PyTorch global runtime settings.

    Reads environment variables for tunable parameters and applies sensible
    production defaults. Intended to be called exactly once at FastAPI startup.

    Environment variables:
        TORCH_NUM_THREADS: Number of intra-op threads (default: 4)
        TORCH_NUM_INTEROP_THREADS: Number of inter-op threads (default: 2)
        TORCH_DETERMINISTIC: Enable deterministic algorithms (default: "1")
        TORCH_MATMUL_PRECISION: float32 matmul precision (default: "high")
    """
    num_threads = int(os.getenv("TORCH_NUM_THREADS", "4"))
    num_interop_threads = int(os.getenv("TORCH_NUM_INTEROP_THREADS", "2"))
    deterministic = os.getenv("TORCH_DETERMINISTIC", "1") == "1"
    matmul_precision = os.getenv("TORCH_MATMUL_PRECISION", "high")

    torch.set_num_threads(num_threads)
    torch.set_num_interop_threads(num_interop_threads)
    torch.set_float32_matmul_precision(matmul_precision)

    if deterministic:
        torch.use_deterministic_algorithms(mode=True, warn_only=True)
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

    logger.info(
        "torch_runtime_configured",
        num_threads=num_threads,
        num_interop_threads=num_interop_threads,
        deterministic=deterministic,
        matmul_precision=matmul_precision,
        cuda_available=torch.cuda.is_available(),
    )
