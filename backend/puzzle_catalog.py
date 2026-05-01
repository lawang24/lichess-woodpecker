from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
PUZZLE_IDS_PATH = DATA_DIR / "puzzle_ids.npy"
PUZZLE_RATINGS_PATH = DATA_DIR / "puzzle_ratings.npy"
RATING_BANDS = [
    (1.0, -200, 200)
]


class CatalogNotBuiltError(RuntimeError):
    pass


class PuzzleCatalog:
    def __init__(self, puzzle_ids: np.ndarray, ratings: np.ndarray):
        if puzzle_ids.shape != ratings.shape:
            raise ValueError("Puzzle catalog arrays must have matching shapes.")

        self.puzzle_ids = puzzle_ids
        self.ratings = ratings
        self.size = int(ratings.shape[0])
        self._rng = np.random.default_rng()

    @classmethod
    def load(cls) -> "PuzzleCatalog":
        if not PUZZLE_IDS_PATH.exists() or not PUZZLE_RATINGS_PATH.exists():
            raise CatalogNotBuiltError(
                "Puzzle catalog is not built. Run '.venv/bin/python build_puzzle_catalog.py' in backend/ first."
            )

        puzzle_ids = np.load(PUZZLE_IDS_PATH, mmap_mode="r")
        ratings = np.load(PUZZLE_RATINGS_PATH, mmap_mode="r")
        return cls(puzzle_ids, ratings)

    def sample_random(self, count: int) -> list[dict]:
        indices = self._pick_random_indices(0, self.size, count)
        return self._rows_from_indices(self._shuffle_indices(indices))

    def sample_by_rating(self, count: int, rating: int) -> list[dict]:
        selected = []
        used = set()

        for weight, low_offset, high_offset in RATING_BANDS:
            sample_size = round(count * weight)
            if sample_size <= 0:
                continue

            start, stop = self._band_slice(rating, low_offset, high_offset)
            for index in self._pick_random_indices(start, stop, sample_size, used):
                used.add(index)
                selected.append(index)

        return self._rows_from_indices(
            self._shuffle_indices(np.asarray(selected, dtype=np.int64))
        )

    def sample_replacement(
        self,
        rating: int | None,
        excluded_puzzle_ids: set[str],
    ) -> dict | None:
        if rating is None:
            return self._sample_one_from_slice(0, self.size, excluded_puzzle_ids)

        for _, low_offset, high_offset in RATING_BANDS:
            start, stop = self._band_slice(rating, low_offset, high_offset)
            replacement = self._sample_one_from_slice(start, stop, excluded_puzzle_ids)
            if replacement is not None:
                return replacement

        return None

    def _band_slice(self, rating: int, low_offset: int, high_offset: int | None):
        low = rating + low_offset
        start_side = "right" if low_offset > 0 else "left"
        start = int(np.searchsorted(self.ratings, low, side=start_side))

        if high_offset is None:
            return start, self.size

        high = rating + high_offset
        stop_side = "left" if high_offset < 0 else "right"
        stop = int(np.searchsorted(self.ratings, high, side=stop_side))
        return start, stop

    def _pick_random_indices(
        self,
        start: int,
        stop: int,
        count: int,
        used: set[int] | None = None,
    ) -> np.ndarray:
        available = stop - start
        if count <= 0 or available <= 0:
            return np.empty(0, dtype=np.int64)

        used = used or set()
        if not used:
            sample_size = min(count, available)
            return start + self._rng.choice(available, size=sample_size, replace=False)

        selected = []
        selected_set = set()

        while len(selected) < count:
            remaining = count - len(selected)
            draw_size = min(available, max(remaining * 2, remaining))
            draw = start + self._rng.choice(available, size=draw_size, replace=False)

            progress = False
            for index in draw.tolist():
                if index in used or index in selected_set:
                    continue
                selected.append(index)
                selected_set.add(index)
                progress = True
                if len(selected) == count:
                    break

            if not progress or len(selected_set) >= available:
                break

        return np.asarray(selected, dtype=np.int64)

    def _rows_from_indices(self, indices: np.ndarray) -> list[dict]:
        if len(indices) == 0:
            return []

        puzzle_ids = self.puzzle_ids[indices]
        ratings = self.ratings[indices]
        return [
            {"puzzle_id": puzzle_id.decode("ascii"), "rating": int(rating)}
            for puzzle_id, rating in zip(puzzle_ids, ratings, strict=True)
        ]

    def _sample_one_from_slice(
        self,
        start: int,
        stop: int,
        excluded_puzzle_ids: set[str],
    ) -> dict | None:
        if stop <= start:
            return None

        indices = self._shuffle_indices(np.arange(start, stop, dtype=np.int64))
        for index in indices:
            puzzle_id = self.puzzle_ids[index].decode("ascii")
            if puzzle_id in excluded_puzzle_ids:
                continue
            return {"puzzle_id": puzzle_id, "rating": int(self.ratings[index])}

        return None

    def _shuffle_indices(self, indices: np.ndarray) -> np.ndarray:
        if len(indices) <= 1:
            return indices
        return self._rng.permutation(indices)
