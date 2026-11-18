"""Qt and PySide6 Environment Bootstrap.

Ensures that PySide6 DLL directories and Qt platform plugin paths
are correctly registered in the Windows dynamic linker search path
and process environment before QApplication is initialized.
Safely clears any conflicting external Qt environment variables.
"""

import os
import sys

# Persistent module-level list to prevent Python's garbage collector from
# destroying DLL directory handles and revoking them via RemoveDllDirectory
_dll_directory_handles = []


def setup_qt_environment() -> None:
    """Configures DLL paths and Qt plugins for Windows and desktop environments."""
    # Suppress Protobuf / OpenCV / absl / Qt DPI awareness noise
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("ABSL_LOG_LEVEL", "3")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false;qt.qpa.*=false;*.debug=false")
    os.environ.setdefault("QT_WIN_WINDOWS_ARGUMENTS", "dpiawareness=0")

    # CRITICAL: Always purge foreign/stale Qt plugin environment variables!
    # If an external software or environment set QT_QPA_PLATFORM_PLUGIN_PATH or QT_PLUGIN_PATH,
    # Qt will attempt to load the foreign platform plugin and crash with:
    # 'This application failed to start because no Qt platform plugin could be initialized.'
    for env_var in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH"):
        if env_var in os.environ:
            try:
                del os.environ[env_var]
            except Exception:
                pass

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetEnvironmentVariableW("QT_QPA_PLATFORM_PLUGIN_PATH", None)
            ctypes.windll.kernel32.SetEnvironmentVariableW("QT_PLUGIN_PATH", None)
        except Exception:
            pass

    try:
        import PySide6

        pyside_dir = os.path.dirname(os.path.abspath(PySide6.__file__))
        shiboken_dir = os.path.join(os.path.dirname(pyside_dir), "shiboken6")
        plugins_dir = os.path.join(pyside_dir, "plugins")
        platforms_dir = os.path.join(plugins_dir, "platforms")

        # Windows Python 3.8+ DLL directory registration and PATH augmentation
        if sys.platform == "win32":
            target_dirs = [pyside_dir, shiboken_dir, plugins_dir, platforms_dir]
            path_dirs = []
            for d in target_dirs:
                if os.path.isdir(d):
                    path_dirs.append(d)
                    if hasattr(os, "add_dll_directory"):
                        try:
                            # CRITICAL: Keep reference so GC does not revoke the directory search path!
                            handle = os.add_dll_directory(d)
                            _dll_directory_handles.append(handle)
                        except Exception:
                            pass

            try:
                import ctypes
                ctypes.windll.kernel32.SetDllDirectoryW(pyside_dir)
            except Exception:
                pass

            if path_dirs:
                curr_path = os.environ.get("PATH", "")
                # Prepend PySide6 directories to ensure our DLLs take precedence
                os.environ["PATH"] = os.pathsep.join(path_dirs) + os.pathsep + curr_path

        # Set QT_PLUGIN_PATH and QT_QPA_PLATFORM_PLUGIN_PATH strictly to PySide6's own directory
        if os.path.isdir(plugins_dir):
            os.environ["QT_PLUGIN_PATH"] = plugins_dir
        if os.path.isdir(platforms_dir):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms_dir
            if sys.platform == "win32":
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetEnvironmentVariableW("QT_QPA_PLATFORM_PLUGIN_PATH", platforms_dir)
                    ctypes.windll.kernel32.SetEnvironmentVariableW("QT_PLUGIN_PATH", plugins_dir)
                except Exception:
                    pass

        try:
            from PySide6.QtCore import QCoreApplication
            # Register PySide6 plugins directory (Qt automatically resolves subfolders like 'platforms')
            if os.path.isdir(plugins_dir):
                QCoreApplication.addLibraryPath(plugins_dir)
        except Exception:
            pass

    except Exception:
        pass


# Run automatically on import
setup_qt_environment()
