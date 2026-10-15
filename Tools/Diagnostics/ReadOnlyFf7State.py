"""Read host state externally. Never inject, write, start or stop a game."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import struct


class ReadOnlyFf7State:
    def __init__(self, pid: int, executable: Path, layout: dict) -> None:
        if hashlib.sha256(executable.read_bytes()).hexdigest() != layout["binary_sha256"]:
            raise ValueError("The host build differs from the analyzed executable")
        self.offsets = layout["offsets"]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ. No write or thread privileges.
        self.handle = self.kernel.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "The specified host process is not readable")
        try:
            name = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(name))
            if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, name, ctypes.byref(length)):
                raise OSError("Cannot verify host process identity")
            if Path(name.value).resolve() != executable.resolve():
                raise ValueError("PID does not belong to the requested host executable")
            modules = (ctypes.c_void_p * 1024)()
            needed = wintypes.DWORD()
            if not self.psapi.EnumProcessModulesEx(self.handle, modules, ctypes.sizeof(modules),
                                                   ctypes.byref(needed), 2):
                raise OSError("Cannot determine host image base")
            if needed.value > ctypes.sizeof(modules) or not modules[0]:
                raise ValueError("Unexpected module inventory")
            self.image_base = int(modules[0])
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def read(self, address: int, size: int) -> bytes:
        if address < 0x10000 or size < 1 or size > 1024:
            raise ValueError("Invalid bounded memory read")
        output = ctypes.create_string_buffer(size)
        actual = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, output, size, ctypes.byref(actual)):
            raise OSError("Host state is not available at this point")
        if actual.value != size:
            raise OSError("Partial host state read")
        return output.raw

    def pointer(self, address: int) -> int:
        return struct.unpack("<Q", self.read(address, 8))[0]

    def snapshot(self, player: int = 0) -> dict:
        if not 0 <= player < 8:
            raise ValueError("Invalid player index")
        offsets = self.offsets
        manager_address = self.image_base + offsets["manager_global_rva"]
        manager = self.pointer(manager_address)
        health_root = self.pointer(manager + offsets["health_root"])
        health_slots = self.pointer(health_root + offsets["health_slots"])
        health = struct.unpack("<i", self.read(health_slots + offsets["health_value"] +
                                               player * offsets["health_player_stride"], 4))[0]
        equipment = self.pointer(manager + offsets["equipment_manager"])
        equipped_slots = self.pointer(equipment + offsets["equipment_slots_pointer"])
        start = equipped_slots + offsets["equipment_slots"] + player * offsets["equipment_player_stride"]
        selected = {
            slot: struct.unpack("<i", self.read(start + offsets["equipment_" + slot], 4))[0]
            for slot in ("weapon", "armor", "accessory")
        }
        if manager != self.pointer(manager_address):
            raise OSError("Host state changed during observation; discard the snapshot")
        return {"player": player, "hp": health, "equipped_slot_identifiers": selected,
                "writes_performed": False, "code_injected": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--layout", type=Path, default=Path("Sheets/host_memory.json"))
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding="utf-8"))["rows"][0]
    observer = ReadOnlyFf7State(args.pid, args.exe, layout)
    try:
        print(json.dumps(observer.snapshot(), indent=2))
    finally:
        observer.close()


if __name__ == "__main__":
    main()
