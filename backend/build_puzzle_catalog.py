import csv
import io

import numpy as np
import zstandard as zstd
from numpy.lib.format import open_memmap

from puzzle_catalog import DATA_DIR, PUZZLE_IDS_PATH, PUZZLE_RATINGS_PATH

PUZZLE_CSV = DATA_DIR / "puzzles.csv.zst"
TEMP_IDS_PATH = DATA_DIR / "puzzle_ids.tmp.npy"
TEMP_RATINGS_PATH = DATA_DIR / "puzzle_ratings.tmp.npy"
CHUNK_SIZE = 250_000


def _iter_puzzle_rows():
    with PUZZLE_CSV.open("rb") as source:
        with zstd.ZstdDecompressor().stream_reader(source) as reader:
            with io.TextIOWrapper(reader, encoding="utf-8", newline="") as text:
                for row in csv.DictReader(text):
                    yield row["PuzzleId"], int(row["Rating"])


def _count_rows() -> int:
    return sum(1 for _ in _iter_puzzle_rows())


def build_puzzle_catalog() -> int:
    row_count = _count_rows()

    temp_ids = open_memmap(TEMP_IDS_PATH, mode="w+", dtype="S5", shape=(row_count,))
    temp_ratings = open_memmap(
        TEMP_RATINGS_PATH, mode="w+", dtype=np.uint16, shape=(row_count,)
    )

    try:
        for index, (puzzle_id, rating) in enumerate(_iter_puzzle_rows()):
            temp_ids[index] = puzzle_id.encode("ascii")
            temp_ratings[index] = rating

        order = np.argsort(temp_ratings, kind="stable")
        sorted_ids = open_memmap(
            PUZZLE_IDS_PATH, mode="w+", dtype="S5", shape=(row_count,)
        )
        sorted_ratings = open_memmap(
            PUZZLE_RATINGS_PATH, mode="w+", dtype=np.uint16, shape=(row_count,)
        )

        for start in range(0, row_count, CHUNK_SIZE):
            stop = min(start + CHUNK_SIZE, row_count)
            chunk_order = order[start:stop]
            sorted_ids[start:stop] = temp_ids[chunk_order]
            sorted_ratings[start:stop] = temp_ratings[chunk_order]

        sorted_ids.flush()
        sorted_ratings.flush()
    except Exception:
        for output_path in (PUZZLE_IDS_PATH, PUZZLE_RATINGS_PATH):
            if output_path.exists():
                output_path.unlink()
        raise
    finally:
        for temp_path in (TEMP_IDS_PATH, TEMP_RATINGS_PATH):
            if temp_path.exists():
                temp_path.unlink()

    return row_count


if __name__ == "__main__":
    print(f"Built compact puzzle catalog with {build_puzzle_catalog()} puzzles.")
