from typing import List


def list_media() -> List[str]:
    return ["demo.mp4", "sample.jpg"]


def play(path: str) -> None:
    print(f"Playing {path}")

