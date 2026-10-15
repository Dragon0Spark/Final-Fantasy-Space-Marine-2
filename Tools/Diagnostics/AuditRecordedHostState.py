"""Check the read-only state layout against the recorded FFVII crash snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

from ReadOnlyFf7State import ReadOnlyFf7State


class RecordedFf7State(ReadOnlyFf7State):
    def __init__(self, dump: Path, offsets: dict) -> None:
        self.data = dump.read_bytes()
        self.offsets = offsets
        if self.data[:4] != b"MDMP":
            raise ValueError("Not a Windows minidump")
        count, directory = struct.unpack_from("<II", self.data, 8)
        streams = {}
        for index in range(count):
            kind, size, offset = struct.unpack_from("<III", self.data, directory + index * 12)
            streams[kind] = (size, offset)
        _, module_stream = streams[4]
        module_count = struct.unpack_from("<I", self.data, module_stream)[0]
        self.image_base = None
        for index in range(module_count):
            offset = module_stream + 4 + 108 * index
            base = struct.unpack_from("<Q", self.data, offset)[0]
            name_offset = struct.unpack_from("<I", self.data, offset + 20)[0]
            name_size = struct.unpack_from("<I", self.data, name_offset)[0]
            name = self.data[name_offset + 4:name_offset + 4 + name_size].decode("utf-16-le")
            if name.lower().endswith("\\ff7remake_.exe"):
                self.image_base = base
        if self.image_base is None:
            raise ValueError("Snapshot does not identify the requested FFVII host")
        self.ranges = []
        if 9 in streams:
            _, offset = streams[9]
            count, contents = struct.unpack_from("<QQ", self.data, offset)
            for index in range(count):
                start, size = struct.unpack_from("<QQ", self.data, offset + 16 + index * 16)
                self.ranges.append((start, size, contents))
                contents += size
        elif 5 in streams:
            _, offset = streams[5]
            count = struct.unpack_from("<I", self.data, offset)[0]
            for index in range(count):
                start, size, contents = struct.unpack_from("<QII", self.data, offset + 4 + index * 16)
                self.ranges.append((start, size, contents))
        else:
            raise ValueError("Snapshot has no recorded memory ranges")

    def read(self, address: int, size: int) -> bytes:
        for start, length, offset in self.ranges:
            if start <= address and address + size <= start + length:
                position = offset + address - start
                return self.data[position:position + size]
        raise OSError("The snapshot did not retain this host-state range")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--layout", type=Path, default=Path("Sheets/host_memory.json"))
    parser.add_argument("--report", type=Path, default=Path("Reports/recorded-host-state.json"))
    args = parser.parse_args()
    offsets = json.loads(args.layout.read_text(encoding="utf-8"))["rows"][0]["offsets"]
    observer = RecordedFf7State(args.dump, offsets)
    try:
        report = {"scope": "recorded crash snapshot, not a live gameplay test",
                  "coverage": "selected fields retained", "state": observer.snapshot()}
    except OSError as error:
        report = {"scope": "recorded crash snapshot, not a live gameplay test",
                  "coverage": "incomplete", "state": None, "limitation": str(error)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
