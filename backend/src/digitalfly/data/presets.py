"""Named run configurations (presets): shipped ones in configs/, and ones saved from the app in configs/local/,
which git ignores.

A preset file holds {"description": ..., "config": RunConfig}; a plain RunConfig file, such as configs/default.json,
is a preset without a description. Every preset is validated in full as a RunConfig when it is saved and whenever it
is read, so a preset that names a missing circuit, or FlyVis eyes without FlyVis, is reported, never applied.
"""
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Annotated
from pydantic import Field, ValidationError
from digitalfly.api.models import CONFIG_SIZE_LIMIT, RunConfig, StrictModel
from digitalfly.simulation.engines import ROOT

CONFIG_DIR = ROOT / "configs"
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
SIZE_LIMIT = CONFIG_SIZE_LIMIT  # bytes per preset file, as for a configuration sent to the API
LOCAL_LIMIT = 200  # presets saved from the app
PresetName = Annotated[str, Field(pattern=rf"^{NAME.pattern}$")]
Description = Annotated[str, Field(max_length=200)]


class PresetFile(StrictModel):
    name: PresetName | None = None
    description: Description = ""
    config: dict


class PresetRequest(StrictModel):
    name: PresetName
    description: Description = ""
    config: RunConfig


class PresetConflict(ValueError):
    """The preset is shipped with DigitalFly (HTTP 409): it cannot be replaced or deleted from the app."""


class PresetUnavailable(ValueError):
    """The preset is valid but needs something this computer lacks, such as FlyVis or a circuit (HTTP 409)."""


class PresetStorageError(OSError):
    """configs/local/ cannot be written, such as in a container without a volume there (HTTP 503)."""


def _folders():
    return [("shipped", CONFIG_DIR), ("local", CONFIG_DIR / "local")]


def writable() -> bool:
    """True when presets can be saved: configs/local/ is a folder this process may write, or can be made in configs/."""
    local = CONFIG_DIR / "local"
    folder = local if local.exists() or local.is_symlink() else CONFIG_DIR
    return folder.is_dir() and os.access(folder, os.W_OK | os.X_OK)


def _path(name: str):
    """The preset file of that name and its source; shipped presets come first and cannot be shadowed."""
    if NAME.fullmatch(name):
        for source, folder in _folders():
            path = folder / f"{name}.json"
            if path.is_file() and not path.is_symlink():
                return path, source
    raise FileNotFoundError(f"There is no preset named {name}.")


def _messages(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, error['loc']))}: {error['msg']}" if error["loc"] else error["msg"]
                     for error in exc.errors())


def summary(config: RunConfig) -> str:
    """A generated description, for plain RunConfig files."""
    model = ("engineered six-unit model" if config.neural_model == "engineered" else
             f"connectome model ({config.connectome_parameters.circuit}, {config.connectome_parameters.dynamics})")
    sensor = {"geometric": "geometric sensing", "vision": "compound-eye vision", "flyvis": "FlyVis eyes"}[config.sensor_model]
    body = "FlyGym body" if config.engine == "flygym" else "toy body"
    return f"{body} · {model} · {sensor}" + (f" · protocol “{config.protocol.name}”" if config.protocol else "")


def read_file(path: Path) -> tuple[str, dict]:
    """A preset file's description and configuration (not yet validated as a RunConfig)."""
    if path.stat().st_size > SIZE_LIMIT:
        raise ValueError(f"The file is larger than {SIZE_LIMIT // 2**20} MB.")
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"The file is not valid JSON: {exc}") from exc
    if isinstance(data, dict) and "config" in data:
        try:
            preset = PresetFile.model_validate(data)
        except ValidationError as exc:
            raise ValueError(_messages(exc)) from exc
        return preset.description, preset.config
    if not isinstance(data, dict):
        raise ValueError("The file holds no configuration object.")
    return "", data


def validate(data: dict) -> RunConfig:
    """Validate in full, circuit files included (call it off the event loop, see models.reads_files_later).
    Raises PresetUnavailable when only an optional install or a circuit is missing, ValueError otherwise."""
    try:
        return RunConfig.model_validate(data)
    except ValidationError as exc:
        message = _messages(exc)
        if data.get("sensor_model") == "flyvis":
            from digitalfly.vision.flyvis_eyes import available
            ok, reason = available()
            if not ok:
                raise PresetUnavailable(reason) from exc
        parameters = data.get("connectome_parameters")
        circuit = parameters.get("circuit") if isinstance(parameters, dict) else None
        if data.get("neural_model") in ("connectome", "connectome_dna02") and isinstance(circuit, str):
            from digitalfly.neural.connectome import circuit_path
            try:
                circuit_path(circuit)
            except FileNotFoundError as missing:
                raise PresetUnavailable(str(missing)) from exc
            except ValueError:
                pass
        raise ValueError(message) from exc


def _load(name: str):
    path, source = _path(name)
    description, data = read_file(path)
    config = validate(data)
    return source, description or summary(config), config


def load(name: str) -> dict:
    """{"name", "source", "description", "config"}. Raises FileNotFoundError, PresetUnavailable or ValueError."""
    source, description, config = _load(name)
    return {"name": name, "source": source, "description": description, "config": config.model_dump()}


def list_presets() -> list[dict]:
    """Every preset, shipped (default first) then local, by name. A preset this computer cannot run is listed with
    "available": false and the reason; an invalid file is listed with an "error" instead of the others failing."""
    result, seen = [], set()
    for source, folder in _folders():
        if not folder.is_dir():
            continue
        paths = [path for path in folder.glob("*.json") if NAME.fullmatch(path.stem) and path.stem not in seen
                 and path.is_file() and not path.is_symlink()]
        for path in sorted(paths, key=lambda p: (p.stem != "default", p.stem)):
            seen.add(path.stem)
            entry = {"name": path.stem, "source": source, "description": "", "available": True}
            try:
                description, data = read_file(path)
                entry["description"] = description
                config = validate(data)
                entry["description"] = description or summary(config)
            except PresetUnavailable as exc:
                entry.update(available=False, reason=str(exc))
            except (OSError, ValueError) as exc:
                entry.update(available=False, error=str(exc))
            result.append(entry)
    return result


def save(request: PresetRequest) -> dict:
    """Save a local preset, replacing one of the same name. The configuration is validated in full first."""
    if (CONFIG_DIR / f"{request.name}.json").exists():
        raise PresetConflict(f"{request.name} is a preset shipped with DigitalFly. Choose another name.")
    config = validate(request.config.model_dump())
    folder = CONFIG_DIR / "local"
    path = folder / f"{request.name}.json"
    if path.is_symlink():
        raise ValueError("That preset name is taken by a link. Choose another name.")
    if not path.exists() and len(list(folder.glob("*.json")) if folder.is_dir() else []) >= LOCAL_LIMIT:
        raise PresetConflict(f"{LOCAL_LIMIT} presets are saved already. Delete one first.")
    text = json.dumps({"name": request.name, "description": request.description, "config": config.model_dump()},
                      indent=2, allow_nan=False) + "\n"
    if len(text.encode()) > SIZE_LIMIT:
        raise ValueError(f"The preset is larger than {SIZE_LIMIT // 2**20} MB.")
    # A new, unpredictable partial file (never one a link stands in for), renamed into place when complete.
    part = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        descriptor, part = tempfile.mkstemp(prefix=f".{request.name}.json.", suffix=".part", dir=folder)
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
        os.replace(part, path)
    except BaseException as exc:
        if part is not None:
            Path(part).unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise PresetStorageError(f"Presets cannot be saved in {folder}: {exc.strerror or exc}. It must be a folder "
                                     "DigitalFly may write; in a container, a volume at /app/configs/local "
                                     "(see docs/INSTALL.md).") from exc
        raise
    return {"name": request.name, "source": "local", "description": request.description or summary(config),
            "config": config.model_dump()}


def delete(name: str) -> dict:
    path, source = _path(name)
    if source == "shipped":
        raise PresetConflict(f"{name} is a preset shipped with DigitalFly and cannot be deleted.")
    path.unlink()
    return {"deleted": name}


def load_config(value: str) -> RunConfig:
    """A RunConfig from a preset name or a preset/RunConfig JSON file (scripts/launch.py --config)."""
    path = Path(value)
    if path.is_file():
        return validate(read_file(path)[1])
    try:
        return _load(value)[2]
    except FileNotFoundError:
        names = ", ".join(entry["name"] for entry in list_presets())
        raise FileNotFoundError(f"{value} is neither a file nor a preset name. Presets: {names or 'none'}.") from None
