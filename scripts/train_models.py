"""Generate simulator datasets (train/validation) and train the predictive bundle.

Usage: uv run python scripts/train_models.py [--rebuild-data]
"""

import argparse
import time

from foresight.artifacts import MODEL_PATH, load_or_build_dataset
from foresight.prediction import save_bundle, train_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-data", action="store_true")
    args = parser.parse_args()

    t0 = time.perf_counter()
    train = load_or_build_dataset("train", rebuild=args.rebuild_data)
    validation = load_or_build_dataset("validation", rebuild=args.rebuild_data)
    print(
        f"datasets: train={train.n_rows} rows/{len(train.episodes)} episodes, "
        f"validation={validation.n_rows} rows/{len(validation.episodes)} episodes "
        f"({time.perf_counter() - t0:.1f}s)"
    )
    t1 = time.perf_counter()
    bundle = train_bundle(train, validation)
    save_bundle(bundle, MODEL_PATH)
    print(f"trained {bundle.version} in {time.perf_counter() - t1:.1f}s -> {MODEL_PATH}")


if __name__ == "__main__":
    main()
