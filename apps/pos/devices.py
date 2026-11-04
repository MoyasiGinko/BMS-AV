"""Hardware device discovery and connectivity helpers for Point of Sale (POS).

Covers physical/network thermal printers, cash drawers, and barcode scanners
on Windows, Linux, and macOS.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import platform
import re
import shutil
import socket
import subprocess
from ctypes import wintypes
from typing import Any

try:
    import winreg
except ImportError:
    winreg = None

logger = logging.getLogger(__name__)

KNOWN_SCANNER_VENDORS: dict[str, str] = {
    "05E0": "Zebra / Symbol",
    "0400": "Zebra Technologies",
    "0C2E": "Honeywell",
    "0536": "Honeywell / HHP",
    "0670": "Intermec",
    "05F9": "Datalogic",
    "1EAB": "Newland",
    "11F3": "Opticon",
    "07F7": "Code Corp",
    "2DD6": "Socket Mobile",
    "24EA": "Netum / Eyoyo",
    "04D9": "Holtek / USB Scanner",
    "16C0": "Generic Barcode Scanner",
    "0483": "POS Barcode Scanner",
    "1A86": "WCH Barcode Scanner",
    "1A2C": "USB Barcode Reader",
    "062A": "MosArt Barcode Scanner",
    "04B4": "Cypress Barcode Scanner",
    "10C4": "Silicon Labs POS Scanner",
    "058F": "Alcor POS Scanner",
    "248A": "Wireless Barcode Scanner",
    "258A": "SinoWealth Barcode Scanner",
    "0603": "Novatek Barcode Scanner",
    "1C4F": "SiGma Micro Scanner",
    "04F3": "Elan POS Scanner",
    "2008": "Symcode Barcode Scanner",
    "0416": "Winbond Barcode Reader",
    "1234": "POS Barcode Scanner",
}


def _parse_printer_type(port: str) -> tuple[str, str]:
    port_lower = port.lower()
    if any(k in port_lower for k in ("wsd", "tcp", "ip", "net")):
        return "wifi", "Wi-Fi"
    if "usb" in port_lower:
        return "usb", "USB"
    return "cable", "Cable"


def _is_printer_online(
    *,
    name: str,
    port: str,
    ptype: str,
    status_flags: int = 0,
    attr_flags: int = 0,
) -> bool:
    """Determine whether a detected hardware printer is online and reachable."""
    if (attr_flags & 0x00000400) or (status_flags & 0x00021080):
        return False

    if ptype == "usb":
        return True

    ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", port)
    target_ip = ip_match.group(1) if ip_match else None

    if not target_ip:
        hex_match = re.search(r"([0-9a-fA-F]{6})", name)
        target_hex = hex_match.group(1).lower() if hex_match else ""
        if target_hex:
            arp_bin = shutil.which("arp") or "arp"
            with contextlib.suppress(Exception):
                res = subprocess.run([arp_bin, "-a"], capture_output=True, text=True, timeout=1, check=False)  # noqa: S603
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        pip, pmac = parts[0], parts[1].lower().replace("-", "")
                        if target_hex in pmac:
                            target_ip = pip
                            break

    if target_ip:
        for port_num in (9100, 80, 631):
            with contextlib.suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect((target_ip, port_num))
                return True
        return False

    return True


def _enum_printers_winspool() -> list[dict[str, Any]]:
    """Discover real physical/network printers on Windows via winspool EnumPrintersW."""
    virtual_keywords = ("pdf", "xps", "onenote", "fax", "anydesk", "document writer")
    try:
        winspool = ctypes.WinDLL("winspool.drv")
        flags = 0x00000002 | 0x00000004

        class PRINTER_INFO_2(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("pServerName", wintypes.LPWSTR),
                ("pPrinterName", wintypes.LPWSTR),
                ("pShareName", wintypes.LPWSTR),
                ("pPortName", wintypes.LPWSTR),
                ("pDriverName", wintypes.LPWSTR),
                ("pComment", wintypes.LPWSTR),
                ("pLocation", wintypes.LPWSTR),
                ("pDevMode", ctypes.c_void_p),
                ("pSepFile", wintypes.LPWSTR),
                ("pPrintProcessor", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR),
                ("pParameters", wintypes.LPWSTR),
                ("pSecurityDescriptor", ctypes.c_void_p),
                ("Attributes", wintypes.DWORD),
                ("Priority", wintypes.DWORD),
                ("DefaultPriority", wintypes.DWORD),
                ("StartTime", wintypes.DWORD),
                ("UntilTime", wintypes.DWORD),
                ("Status", wintypes.DWORD),
                ("cJobs", wintypes.DWORD),
                ("AveragePPM", wintypes.DWORD),
            ]

        needed = wintypes.DWORD()
        returned = wintypes.DWORD()
        winspool.EnumPrintersW(flags, None, 2, None, 0, ctypes.byref(needed), ctypes.byref(returned))
        if needed.value > 0:
            buf = ctypes.create_string_buffer(needed.value)
            if winspool.EnumPrintersW(flags, None, 2, buf, needed.value, ctypes.byref(needed), ctypes.byref(returned)):
                items = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2))
                fast_printers: list[dict[str, Any]] = []
                for i in range(returned.value):
                    p = items[i]
                    name = p.pPrinterName or ""
                    driver = p.pDriverName or ""
                    port = p.pPortName or ""
                    if any(vk in name.lower() or vk in driver.lower() for vk in virtual_keywords):
                        continue
                    ptype, badge = _parse_printer_type(port)
                    is_online = _is_printer_online(
                        name=name,
                        port=port,
                        ptype=ptype,
                        status_flags=p.Status,
                        attr_flags=p.Attributes,
                    )
                    fast_printers.append({
                        "id": name,
                        "name": name,
                        "type": ptype,
                        "badge": badge,
                        "port": port,
                        "driver": driver,
                        "is_online": is_online,
                    })
                return fast_printers
    except Exception as exc:
        logger.debug("Winspool EnumPrintersW fast path error: %s", exc)
    return []


def _get_windows_printers() -> list[dict[str, Any]]:
    """Discover real physical/network printers on Windows."""
    printers = _enum_printers_winspool()
    if printers:
        return printers

    virtual_keywords = ("pdf", "xps", "onenote", "fax", "anydesk", "document writer")
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-Printer | Select-Object Name, Type, DriverName, PortName, PrinterStatus | ConvertTo-Json -Compress",
    ]
    printers_out: list[dict[str, Any]] = []
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)  # noqa: S603
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            for p in data:
                name = p.get("Name") or ""
                driver = p.get("DriverName") or ""
                port = p.get("PortName") or ""
                if any(vk in name.lower() or vk in driver.lower() for vk in virtual_keywords):
                    continue
                ptype, badge = _parse_printer_type(port)
                is_online = _is_printer_online(
                    name=name,
                    port=port,
                    ptype=ptype,
                )
                printers_out.append({
                    "id": name,
                    "name": name,
                    "type": ptype,
                    "badge": badge,
                    "port": port,
                    "driver": driver,
                    "is_online": is_online,
                })
    except Exception as exc:
        logger.debug("Windows printer discovery error: %s", exc)
    return printers_out


def _get_unix_printers() -> list[dict[str, Any]]:
    lpstat_bin = shutil.which("lpstat")
    if not lpstat_bin:
        return []
    printers: list[dict[str, Any]] = []
    try:
        res = subprocess.run([lpstat_bin, "-p"], capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
        for line in res.stdout.splitlines():
            if line.startswith("printer "):
                pname = line.split()[1]
                printers.append({
                    "id": pname,
                    "name": pname,
                    "type": "network",
                    "badge": "Network",
                    "port": "",
                    "driver": "",
                    "is_online": True,
                })
    except Exception as exc:
        logger.debug("Unix printer discovery error: %s", exc)
    return printers


def get_system_printers() -> list[dict[str, Any]]:
    """Discover real physical/network printers connected to the host system."""
    sys_name = platform.system()
    if sys_name == "Windows":
        return _get_windows_printers()
    if sys_name in ("Linux", "Darwin"):
        return _get_unix_printers()
    return []


def _read_registry_friendly_name(dev_path: str, inst_id: str) -> str:
    """Read friendly name or device description from Windows registry."""
    if winreg is None:
        return ""
    with contextlib.suppress(OSError), winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{dev_path}\\{inst_id}") as inst_key:
        for v in ("FriendlyName", "DeviceDesc"):
            with contextlib.suppress(OSError):
                val, _ = winreg.QueryValueEx(inst_key, v)
                if val:
                    return str(val).split(";")[-1]
    return ""


def _inspect_usb_device_instance(
    *,
    dev_path: str,
    dev_id: str,
    inst_id: str,
    vendor_name: str | None,
) -> dict[str, Any] | None:
    """Check a single USB device instance in Windows registry and test presence."""
    full_inst = f"USB\\{dev_id}\\{inst_id}"
    friendly_name = _read_registry_friendly_name(dev_path, inst_id)

    is_scanner = bool(vendor_name) or any(
        k in friendly_name.lower()
        for k in ("scanner", "barcode", "symbol", "zebra", "honeywell", "datalogic")
    )
    if not is_scanner:
        return None

    cfgmgr32 = ctypes.windll.cfgmgr32
    dev_inst = wintypes.DWORD()
    cr = cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(dev_inst), full_inst, 0)
    if cr != 0:
        return None

    name = vendor_name or friendly_name or "Barcode Scanner"
    serial = ""
    if "S/N:" in inst_id:
        serial = inst_id.rsplit("S/N:", maxsplit=1)[-1].split("_", maxsplit=1)[0]

    return {
        "id": full_inst,
        "name": name,
        "type": "USB",
        "badge": "USB",
        "vendor": vendor_name or "Generic",
        "serial": serial,
        "is_online": True,
    }


def _scan_windows_registry_scanners() -> list[dict[str, Any]]:
    """Fast-path discovery of USB barcode scanners using Windows registry and cfgmgr32."""
    if winreg is None:
        return []
    found: list[dict[str, Any]] = []
    base_path = r"SYSTEM\CurrentControlSet\Enum\USB"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path) as usb_key:
            sub_idx = 0
            while True:
                try:
                    dev_id = winreg.EnumKey(usb_key, sub_idx)
                    sub_idx += 1
                except OSError:
                    break

                vid_match = re.search(r"VID_([0-9A-Fa-f]{4})", dev_id)
                vid = vid_match.group(1).upper() if vid_match else None
                vendor_name = KNOWN_SCANNER_VENDORS.get(vid) if vid else None

                dev_path = f"{base_path}\\{dev_id}"
                with contextlib.suppress(OSError), winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dev_path) as dev_key:
                    inst_idx = 0
                    while True:
                        try:
                            inst_id = winreg.EnumKey(dev_key, inst_idx)
                            inst_idx += 1
                        except OSError:
                            break

                        sc = _inspect_usb_device_instance(
                            dev_path=dev_path,
                            dev_id=dev_id,
                            inst_id=inst_id,
                            vendor_name=vendor_name,
                        )
                        if sc:
                            found.append(sc)
    except Exception as exc:
        logger.debug("Winreg fast scanner discovery error: %s", exc)
    return found


def _scan_windows_pnp_scanners() -> list[dict[str, Any]]:
    """Fallback discovery of barcode scanners on Windows via PowerShell Get-PnpDevice."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-PnpDevice -Status OK -Class HIDClass, POS, Ports | Select-Object FriendlyName, InstanceId | ConvertTo-Json -Compress",
    ]
    found: list[dict[str, Any]] = []
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                inst = (d.get("InstanceId") or "").upper()
                name = d.get("FriendlyName") or ""
                vendor_match = None
                for vid, vname in KNOWN_SCANNER_VENDORS.items():
                    if f"VID_{vid}" in inst:
                        vendor_match = vname
                        break
                if vendor_match or any(k in name.lower() for k in ("scanner", "barcode")):
                    found.append({
                        "id": inst,
                        "name": vendor_match or name or "Barcode Scanner",
                        "type": "USB",
                        "badge": "USB",
                        "vendor": vendor_match or "Generic",
                        "serial": "",
                        "is_online": True,
                    })
    except Exception as exc:
        logger.debug("PowerShell scanner discovery error: %s", exc)
    return found


def _get_windows_scanners() -> list[dict[str, Any]]:
    """Discover real physical/network barcode scanners connected on Windows."""
    scanners = _scan_windows_registry_scanners()
    if scanners:
        return scanners
    return _scan_windows_pnp_scanners()


def _get_unix_scanners() -> list[dict[str, Any]]:
    """Discover connected barcode scanners on Linux / macOS."""
    lsusb_bin = shutil.which("lsusb")
    if not lsusb_bin:
        return []
    scanners: list[dict[str, Any]] = []
    try:
        res = subprocess.run([lsusb_bin], capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
        for line in res.stdout.splitlines():
            line_upper = line.upper()
            for vid, vname in KNOWN_SCANNER_VENDORS.items():
                if vid in line_upper or any(k in line.lower() for k in ("barcode", "scanner")):
                    scanners.append({
                        "id": line.strip(),
                        "name": vname or "Barcode Scanner",
                        "type": "USB",
                        "badge": "USB",
                        "vendor": vname or "Generic",
                        "serial": "",
                        "is_online": True,
                    })
                    break
    except Exception as exc:
        logger.debug("Unix scanner discovery error: %s", exc)
    return scanners


def get_system_scanners() -> list[dict[str, Any]]:
    """Discover real physical/network barcode scanners connected to the host system."""
    sys_name = platform.system()
    scanners: list[dict[str, Any]] = []
    if sys_name == "Windows":
        scanners = _get_windows_scanners()
    elif sys_name in ("Linux", "Darwin"):
        scanners = _get_unix_scanners()

    if not scanners:
        scanners.append({
            "id": "system_auto_hid",
            "name": "Barcode Scanner (USB / HID)",
            "type": "USB",
            "badge": "Auto",
            "vendor": "System Keyboard Wedge",
            "serial": "",
            "is_online": True,
        })

    return scanners
