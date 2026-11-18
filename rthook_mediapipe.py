"""PyInstaller runtime hook for N.E.X.U.S.
Executes before the main application script is loaded in frozen builds.
"""

import sys
import types

# 1. Guarantee valid stdout and stderr in GUI/windowed mode on Windows
class _SafeNullStream:
    def write(self, s):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _SafeNullStream()
if sys.stderr is None:
    sys.stderr = _SafeNullStream()

# 2. Stub out mediapipe tasks and genai to prevent circular import failures in frozen build
tasks_mod = types.ModuleType("mediapipe.tasks")
tasks_python_mod = types.ModuleType("mediapipe.tasks.python")
tasks_python_mod.BaseOptions = object
tasks_mod.python = tasks_python_mod

for _name in (
    "mediapipe.tasks",
    "mediapipe.tasks.python",
    "mediapipe.tasks.python.audio",
    "mediapipe.tasks.python.components",
    "mediapipe.tasks.python.core",
    "mediapipe.tasks.python.genai",
    "mediapipe.tasks.python.genai.converter",
    "mediapipe.tasks.python.genai.bundler",
    "mediapipe.tasks.python.text",
    "mediapipe.tasks.python.vision",
):
    if _name not in sys.modules:
        _sub = types.ModuleType(_name)
        _sub.BaseOptions = object
        sys.modules[_name] = _sub

sys.modules["mediapipe.tasks"] = tasks_mod
sys.modules["mediapipe.tasks.python"] = tasks_python_mod

# 3. Safeguard against missing matplotlib in drawing_utils
if "matplotlib" not in sys.modules:
    try:
        import matplotlib
        import matplotlib.pyplot
    except Exception:
        _mpl = types.ModuleType("matplotlib")
        _plt = types.ModuleType("matplotlib.pyplot")
        _mpl.pyplot = _plt
        sys.modules["matplotlib"] = _mpl
        sys.modules["matplotlib.pyplot"] = _plt
