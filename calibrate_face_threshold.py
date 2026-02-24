import argparse
import csv
import numpy as np

from pathlib import Path


def _load_scores(path: Path) -> np.ndarray:
    values = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            cell = (row[0] or "").strip()
            if not cell:
                continue
            try:
                values.append(float(cell))
            except ValueError:
                continue
    arr = np.array(values, dtype=np.float32)
    if arr.size == 0:
        raise ValueError(f"No numeric scores found in {path}")
    return arr


def _rate_metrics(genuine: np.ndarray, impostor: np.ndarray, threshold: float) -> tuple[float, float]:
    frr = float(np.mean(genuine < threshold))
    far = float(np.mean(impostor >= threshold))
    return frr, far


def _suggest_threshold(genuine: np.ndarray, impostor: np.ndarray, target_far: float) -> float:
    candidates = np.unique(np.concatenate([genuine, impostor]))
    best = float(np.min(candidates))
    for th in candidates:
        _, far = _rate_metrics(genuine, impostor, float(th))
        if far <= target_far:
            best = float(th)
    return best


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate face similarity thresholds from score samples."
    )
    parser.add_argument("--genuine", required=True, help="CSV with genuine-match scores (1 score per row).")
    parser.add_argument("--impostor", required=True, help="CSV with impostor scores (1 score per row).")
    parser.add_argument("--target-far", type=float, default=0.01, help="Target FAR (default: 0.01).")
    args = parser.parse_args()

    genuine = _load_scores(Path(args.genuine))
    impostor = _load_scores(Path(args.impostor))

    threshold = _suggest_threshold(genuine, impostor, target_far=args.target_far)
    frr, far = _rate_metrics(genuine, impostor, threshold)

    print(f"Samples: genuine={genuine.size}, impostor={impostor.size}")
    print(f"Suggested threshold: {threshold:.4f}")
    print(f"At threshold {threshold:.4f}: FAR={far:.4%}, FRR={frr:.4%}")
    print("")
    print("Set env vars as needed:")
    print(f"  FACE_VERIFY_SIM_THRESHOLD={threshold:.4f}")
    print(f"  FACE_IDENTIFY_SIM_THRESHOLD={max(0.0, threshold - 0.03):.4f}")


if __name__ == "__main__":
    main()
