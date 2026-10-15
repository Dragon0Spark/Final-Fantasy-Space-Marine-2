"""Adapt an installed asset parser to read asset parts without disk extraction."""

from __future__ import annotations

import contextlib
import importlib
import io
from collections.abc import Mapping


class MemoryUnrealAsset:
    def __init__(self, parts: Mapping[str, bytes]) -> None:
        self.parts = dict(parts)

    def read(self, stem: str, version: str = "ff7r"):
        asset_module = importlib.import_module("bua.unreal.uasset")
        export_module = importlib.import_module("bua.unreal.uexp")
        previous = []
        try:
            for module in (asset_module, export_module):
                previous.append((module, "open", getattr(module, "open", None), "open" in vars(module)))
                module.open = self.open_part
            previous.append((export_module, "os", export_module.os, True))
            export_module.os = self.OsView(export_module.os, self.parts)
            with contextlib.redirect_stdout(io.StringIO()):
                return asset_module.Uasset(stem + ".uasset", version=version)
        finally:
            for module, name, value, existed in reversed(previous):
                if existed:
                    setattr(module, name, value)
                else:
                    delattr(module, name)

    def open_part(self, name: str, mode: str):
        if mode != "rb":
            raise PermissionError("The in-memory game content adapter is read-only")
        if name not in self.parts:
            raise FileNotFoundError(name)
        return io.BytesIO(self.parts[name])

    class OsView:
        def __init__(self, original, parts) -> None:
            self.original = original
            self.path = self.PathView(original.path, parts)

        def __getattr__(self, name):
            return getattr(self.original, name)

        class PathView:
            def __init__(self, original, parts) -> None:
                self.original = original
                self.parts = parts

            def exists(self, name):
                return name in self.parts

            def __getattr__(self, name):
                return getattr(self.original, name)
