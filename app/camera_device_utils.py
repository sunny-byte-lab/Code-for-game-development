"""JARVIS Camera Device Utilities & Privacy Diagnostic Engine.
Provides low-level DirectShow device probing, Windows 10/11 camera privacy permission checking,
and HUD notification rendering when OS-level access is blocked.
"""

import sys
import os
import time
import logging
import ctypes
from ctypes import wintypes, byref, c_void_p, POINTER, Structure, HRESULT
from typing import List, Dict, Any, Tuple
import numpy as np
import cv2

logger = logging.getLogger("NEXUS.CameraUtils")

ole32 = getattr(ctypes.windll, "ole32", None)
oleaut32 = getattr(ctypes.windll, "oleaut32", None)


class VARIANT(Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("llVal", ctypes.c_int64),
    ]


class GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]

    def __init__(self, s: str):
        if ole32:
            ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(self))


CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}")
CLSID_VideoInputDeviceCategory = GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
IID_ICreateDevEnum = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
IID_IBaseFilter = GUID("{56a86895-0ad4-11ce-b03a-0020af0ba770}")
IID_IPropertyBag = GUID("{55272A00-42CB-11CE-8135-00AA004BB851}")

E_ACCESSDENIED = 0x80070005


def probe_camera_devices() -> List[Dict[str, Any]]:
    """Probes all DirectShow video input devices on Windows, extracting names,
    virtual driver flags, and hardware access permission status.
    """
    devices: List[Dict[str, Any]] = []
    if not ole32 or not oleaut32 or sys.platform != "win32":
        return devices

    ole32.CoInitialize(None)
    try:
        pDevEnum = c_void_p()
        hr = ole32.CoCreateInstance(
            byref(CLSID_SystemDeviceEnum),
            None,
            1,  # CLSCTX_INPROC_SERVER
            byref(IID_ICreateDevEnum),
            byref(pDevEnum)
        )
        if hr != 0 or not pDevEnum.value:
            return devices

        vtbl_ICreateDevEnum = ctypes.cast(
            ctypes.cast(pDevEnum, POINTER(c_void_p)).contents,
            POINTER(ctypes.c_void_p)
        )
        CreateClassEnumerator_type = ctypes.WINFUNCTYPE(
            HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p), wintypes.DWORD
        )
        CreateClassEnumerator = CreateClassEnumerator_type(vtbl_ICreateDevEnum[3])
        pEnum = c_void_p()
        hr = CreateClassEnumerator(pDevEnum, byref(CLSID_VideoInputDeviceCategory), byref(pEnum), 0)

        if hr != 0 or not pEnum.value:
            return devices

        vtbl_IEnumMoniker = ctypes.cast(
            ctypes.cast(pEnum, POINTER(c_void_p)).contents,
            POINTER(ctypes.c_void_p)
        )
        Next_type = ctypes.WINFUNCTYPE(
            HRESULT, c_void_p, wintypes.ULONG, POINTER(c_void_p), POINTER(wintypes.ULONG)
        )
        Next = Next_type(vtbl_IEnumMoniker[3])

        idx = 0
        while True:
            pMon = c_void_p()
            fetched = wintypes.ULONG(0)
            res = Next(pEnum, 1, byref(pMon), byref(fetched))
            if fetched.value == 0 or not pMon.value:
                break

            vtbl_IMoniker = ctypes.cast(
                ctypes.cast(pMon, POINTER(c_void_p)).contents,
                POINTER(ctypes.c_void_p)
            )

            # 1. Read Friendly Name via IPropertyBag
            friendly_name = f"Camera #{idx}"
            BindToStorage_type = ctypes.WINFUNCTYPE(
                HRESULT, c_void_p, c_void_p, c_void_p, POINTER(GUID), POINTER(c_void_p)
            )
            BindToStorage = BindToStorage_type(vtbl_IMoniker[9])
            pPropBag = c_void_p()
            if BindToStorage(pMon, None, None, byref(IID_IPropertyBag), byref(pPropBag)) == 0 and pPropBag.value:
                vtbl_IProp = ctypes.cast(
                    ctypes.cast(pPropBag, POINTER(c_void_p)).contents,
                    POINTER(ctypes.c_void_p)
                )
                Read_type = ctypes.WINFUNCTYPE(
                    HRESULT, c_void_p, wintypes.LPCWSTR, POINTER(VARIANT), c_void_p
                )
                Read = Read_type(vtbl_IProp[3])
                var = VARIANT()
                oleaut32.VariantInit(byref(var))
                try:
                    if Read(pPropBag, "FriendlyName", byref(var), None) == 0 and var.vt == 8:
                        friendly_name = ctypes.wstring_at(var.llVal)
                except Exception:
                    pass
                oleaut32.VariantClear(byref(var))
                # Release property bag
                Release_type = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
                Release_type(vtbl_IProp[2])(pPropBag)

            # Check if this is a virtual software driver (e.g. Vivo, OBS, DroidCam, etc.)
            name_lower = friendly_name.lower()
            is_virtual = any(k in name_lower for k in ["virtual", "vivo", "obs", "droidcam", "iriun", "vysor", "epoccam"])

            is_permission_denied = False
            is_accessible = False
            error_reason = ""

            if is_virtual:
                # Virtual software drivers do not enforce Windows UVC hardware privacy restrictions.
                # Do NOT call BindToObject during probing on virtual drivers: binding to virtual cameras
                # like Vivo causes the vendor filter DLL to spawn daemon processes (e.g. pcsuite / shareCamera)
                # and emit noisy IPC logs to stdout.
                is_accessible = True
                is_permission_denied = False
                error_reason = ""
            else:
                # 2. Test Hardware Filter Creation (BindToObject) to detect Windows Privacy Lock on physical webcams
                BindToObject_type = ctypes.WINFUNCTYPE(
                    HRESULT, c_void_p, c_void_p, c_void_p, POINTER(GUID), POINTER(c_void_p)
                )
                BindToObject = BindToObject_type(vtbl_IMoniker[8])
                pFilter = c_void_p()

                try:
                    hr_bind = BindToObject(pMon, None, None, byref(IID_IBaseFilter), byref(pFilter))
                    hr_u = hr_bind if hr_bind >= 0 else hr_bind + (1 << 32)
                    if hr_u == 0 and pFilter.value:
                        is_accessible = True
                        vtbl_IFilter = ctypes.cast(
                            ctypes.cast(pFilter, POINTER(c_void_p)).contents,
                            POINTER(ctypes.c_void_p)
                        )
                        Release_type = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
                        Release_type(vtbl_IFilter[2])(pFilter)
                    elif hr_u == E_ACCESSDENIED:
                        is_permission_denied = True
                        error_reason = "Access Denied by Windows Privacy Settings (0x80070005)"
                    else:
                        error_reason = f"Binding failed (hr={hex(hr_u)})"
                except PermissionError:
                    is_permission_denied = True
                    error_reason = "Access Denied by Windows Privacy Settings (0x80070005)"
                except Exception as e:
                    error_reason = str(e)

            devices.append({
                "index": idx,
                "name": friendly_name,
                "is_accessible": is_accessible,
                "is_permission_denied": is_permission_denied,
                "is_virtual": is_virtual,
                "error_reason": error_reason,
            })

            # Release moniker
            Release_type = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
            Release_type(vtbl_IMoniker[2])(pMon)
            idx += 1

    except Exception as ex:
        logger.error(f"Error during DirectShow device probe: {ex}")
    finally:
        ole32.CoUninitialize()

    return devices


def check_camera_permission(device_index: int = 0) -> Tuple[bool, str]:
    """Checks whether the specified camera device is permitted by Windows Camera Privacy.
    Returns (has_permission, reason_if_denied).
    """
    devs = probe_camera_devices()
    for d in devs:
        if d["index"] == device_index:
            if d.get("is_virtual", False):
                return True, ""
            if d["is_permission_denied"]:
                # Verify directly via OpenCV to avoid DirectShow false-positives on Windows 11 UVC cameras
                try:
                    test_cap = cv2.VideoCapture(device_index)
                    if test_cap and test_cap.isOpened():
                        test_cap.release()
                        return True, ""
                except Exception:
                    pass
                return False, d["error_reason"]
            return True, ""
    # If device was not probed, try generic open
    return True, ""


def get_best_camera_index(preferred_index: int = 0) -> int:
    """Selects the best available camera index, prioritizing physical hardware webcams
    over software/virtual drivers (e.g. Vivo Virtual Camera, OBS, DroidCam).
    """
    try:
        devs = probe_camera_devices()
        if not devs:
            return preferred_index

        dev_map = {d["index"]: d for d in devs}

        # 1. If preferred_index is an accessible physical hardware camera, preserve it
        if (
            preferred_index in dev_map
            and not dev_map[preferred_index].get("is_virtual", False)
            and dev_map[preferred_index].get("is_accessible", True)
            and not dev_map[preferred_index].get("is_permission_denied", False)
        ):
            return preferred_index

        # 2. Prioritize accessible physical hardware camera over virtual drivers
        for d in devs:
            if (
                not d.get("is_virtual", False)
                and d.get("is_accessible", True)
                and not d.get("is_permission_denied", False)
            ):
                return d["index"]

        # 3. If preferred_index is accessible (even if virtual, e.g. Vivo Virtual Camera), use it
        if preferred_index in dev_map and dev_map[preferred_index].get("is_accessible", True) and not dev_map[preferred_index].get("is_permission_denied", False):
            return preferred_index

        # 4. Fallback to any accessible camera (virtual or physical)
        for d in devs:
            if d.get("is_accessible", True) and not d.get("is_permission_denied", False):
                return d["index"]

        # 5. Fallback to any physical camera
        for d in devs:
            if not d.get("is_virtual", False):
                return d["index"]

        # 6. Fallback to preferred or first available
        return preferred_index if preferred_index in dev_map else devs[0]["index"]
    except Exception:
        return preferred_index


def open_windows_camera_settings() -> bool:
    """Attempts to launch the Windows Camera Privacy settings page."""
    try:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("ms-settings:privacy-webcam"))
        return True
    except Exception:
        try:
            os.startfile("ms-settings:privacy-webcam")
            return True
        except Exception as e:
            logger.error(f"Failed to open Windows settings: {e}")
            return False


def generate_privacy_blocked_frame(width: int = 640, height: int = 480, frame_count: int = 0) -> np.ndarray:
    """Generates a high-tech Stark Industries HUD notification frame
    explaining that Windows Camera Privacy is blocking webcam access.
    """
    # Dark high-tech background: deep navy
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (18, 12, 7)  # BGR

    # Draw grid background lines
    grid_color = (35, 25, 14)
    for x in range(0, width, 40):
        cv2.line(frame, (x, 0), (x, height), grid_color, 1)
    for y in range(0, height, 40):
        cv2.line(frame, (0, y), (width, y), grid_color, 1)

    # Pulsing warning glow
    pulse = int(127 + 128 * np.sin(frame_count * 0.1))
    alert_color = (0, pulse, 255)  # Amber to bright gold pulse
    cyan = (255, 200, 0)
    white = (240, 240, 240)
    red = (40, 40, 220)

    # Corner brackets (HUD framing)
    bracket_len = 28
    thick = 2
    cv2.line(frame, (20, 20), (20 + bracket_len, 20), cyan, thick)
    cv2.line(frame, (20, 20), (20, 20 + bracket_len), cyan, thick)
    cv2.line(frame, (width - 20, 20), (width - 20 - bracket_len, 20), cyan, thick)
    cv2.line(frame, (width - 20, 20), (width - 20, 20 + bracket_len), cyan, thick)
    cv2.line(frame, (20, height - 20), (20 + bracket_len, height - 20), cyan, thick)
    cv2.line(frame, (20, height - 20), (20, height - 20 - bracket_len), cyan, thick)
    cv2.line(frame, (width - 20, height - 20), (width - 20 - bracket_len, height - 20), cyan, thick)
    cv2.line(frame, (width - 20, height - 20), (width - 20, height - 20 - bracket_len), cyan, thick)

    # Top Banner
    cv2.rectangle(frame, (35, 30), (width - 35, 68), (30, 20, 10), -1)
    cv2.rectangle(frame, (35, 30), (width - 35, 68), alert_color, 1)
    cv2.putText(frame, "// SECURITY NOTICE: OPTICAL SENSOR ACCESS RESTRICTED", (48, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, alert_color, 1, cv2.LINE_AA)

    # Main Center Alert Box
    cv2.rectangle(frame, (45, 95), (width - 45, 385), (24, 16, 9), -1)
    cv2.rectangle(frame, (45, 95), (width - 45, 385), (60, 45, 25), 1)

    # Shield / Warning Symbol
    center_x = width // 2
    cv2.circle(frame, (center_x, 140), 28, alert_color, 2)
    cv2.putText(frame, "!", (center_x - 6, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.1, alert_color, 3, cv2.LINE_AA)

    # Big Headline
    title_text = "WINDOWS WEBCAM PERMISSION BLOCKED"
    (tw, _), _ = cv2.getTextSize(title_text, cv2.FONT_HERSHEY_SIMPLEX, 0.58, 2)
    cv2.putText(frame, title_text, (center_x - tw // 2, 195),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 220, 255), 2, cv2.LINE_AA)

    err_sub = "[ HRESULT 0x80070005 : ACCESS DENIED BY OS ]"
    (sw, _), _ = cv2.getTextSize(err_sub, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)
    cv2.putText(frame, err_sub, (center_x - sw // 2, 218),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (100, 100, 255), 1, cv2.LINE_AA)

    # Instructions
    cv2.putText(frame, "HOW TO RESTORE HARDWARE OPTICAL ACCESS:", (65, 255),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, cyan, 1, cv2.LINE_AA)

    cv2.putText(frame, "1. Click [FIX CAMERA PERMISSION] button in header bar", (75, 282),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, white, 1, cv2.LINE_AA)

    cv2.putText(frame, "2. Under 'Let desktop apps access your camera', toggle to ON", (75, 308),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, white, 1, cv2.LINE_AA)

    cv2.putText(frame, "3. Ensure laptop physical privacy shutter is opened", (75, 334),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, white, 1, cv2.LINE_AA)

    # Bottom auto-retry scanline
    scan_y = 355
    cv2.putText(frame, ">> N.E.X.U.S. AUTO-RETRY ACTIVE -- WAITING FOR PERMISSION GRANT...", (65, scan_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 180), 1, cv2.LINE_AA)

    # Scan progress bar
    bar_width = width - 130
    bar_x = 65
    bar_y = 368
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_width, bar_y + 4), (50, 40, 20), -1)
    indicator_pos = int((frame_count * 4) % bar_width)
    cv2.rectangle(frame, (bar_x + max(0, indicator_pos - 30), bar_y),
                  (bar_x + min(bar_width, indicator_pos + 30), bar_y + 4), (0, 255, 200), -1)

    # Footer note
    cv2.putText(frame, "N.E.X.U.S. // OPTICAL SENSOR TELEMETRY SUBSYSTEM", (center_x - 170, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (100, 100, 100), 1, cv2.LINE_AA)

    return frame
