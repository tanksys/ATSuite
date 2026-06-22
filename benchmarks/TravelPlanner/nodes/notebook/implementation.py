import json
from io import StringIO
from pathlib import Path
import shutil

import pandas as pd
from pandas import DataFrame

from atsuite_sdk.abstract import registry
from atsuite_sdk.state import register_state_object, session_open, session_path

class Notebook:
    def __init__(self) -> None:
        self.write_count = 0
        print("Notebook loaded.")

    def _entries_relpath(self) -> str:
        return "notebook/entries.jsonl"

    def _load_all(self) -> list[dict]:
        try:
            with session_open(self._entries_relpath(), "r", encoding="utf-8") as handle:
                lines = [line.strip() for line in handle.readlines() if line.strip()]
        except FileNotFoundError:
            return []
        return [json.loads(l) for l in lines]

    def _save_all(self, data: list[dict]) -> None:
        with session_open(self._entries_relpath(), "w", encoding="utf-8") as handle:
            for item in data:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def write(self, input_data: DataFrame, short_description: str):
        record = {
            "content": input_data.to_dict(orient="records"),
            "short_description": short_description,
        }
        with session_open(self._entries_relpath(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.write_count += 1
        return f"The information has been recorded in Notebook, and its index is {len(self._load_all()) - 1}."
    
    def update(self, input_data: DataFrame, index: int, short_description: str):
        data = self._load_all()

        if index < 0 or index >= len(data):
            raise IndexError("Notebook index out of range")

        data[index] = {
            "content": input_data.to_dict(orient="records"),
            "short_description": short_description,
        }
        self._save_all(data)
        return "The information has been updated in Notebook."
    
    def list(self):
        data = self._load_all()
        return [
            {
                "index": i,
                "short_description": d["short_description"],
            }
            for i, d in enumerate(data)
        ]

    def list_all(self):
        return self._load_all()
    
    def read(self, index):
        data = self._load_all()
        if index < 0 or index >= len(data):
            raise IndexError("Notebook index out of range")
        return data[index]
    
    def reset(self):
        notebook_dir = Path(session_path("notebook"))
        if notebook_dir.exists():
            shutil.rmtree(notebook_dir)
        self.write_count = 0
        return "Notebook has been reset."

notebook = Notebook()
register_state_object("notebook", notebook)

@registry.tool(stateful=True)
def notebook_write(input_data: str, short_description: str):
    df = pd.read_json(StringIO(input_data), orient="records")
    return notebook.write(df, short_description)


@registry.tool(stateful=True)
def notebook_update(input_data: str, index: int, short_description: str):
    df = pd.read_json(StringIO(input_data), orient="records")
    return notebook.update(df, index, short_description)


@registry.tool()
def notebook_list():
    return notebook.list()


@registry.tool()
def notebook_list_all():
    return notebook.list_all()


@registry.tool()
def notebook_read(index: int):
    return notebook.read(index)


@registry.tool(stateful=True)
def notebook_reset():
    return notebook.reset()
