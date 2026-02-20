#!/usr/bin/env python3
"""
mtp_pull.py - Access Kindle Scribe via MTP in a single persistent connection.

Uses ctypes to call libmtp directly, maintaining one connection for all
operations (avoids the reconnection/dropout issue with CLI tools on macOS).

Usage:
    python3 mtp_pull.py --detect                          # Check if device is connected
    python3 mtp_pull.py --list                             # List all files
    python3 mtp_pull.py --search "pattern"                 # Search filenames
    python3 mtp_pull.py --folders                          # Show folder tree
    python3 mtp_pull.py --get FILE_ID OUTPUT_PATH          # Download a file
    python3 mtp_pull.py --get-many ID1:out1 ID2:out2 ...   # Download multiple
    python3 mtp_pull.py --send LOCAL_PATH PARENT_ID        # Upload a file
    python3 mtp_pull.py --notebooks                        # List notebook GUID folders
    python3 mtp_pull.py --pull-notebooks OUTPUT_DIR        # Download all changed notebooks
"""

import ctypes
import ctypes.util
import argparse
import json
import sys
import os
import time

# ---------------------------------------------------------------------------
# Load libmtp
# ---------------------------------------------------------------------------

LIBMTP_PATH = "/opt/homebrew/lib/libmtp.dylib"
if not os.path.exists(LIBMTP_PATH):
    found = ctypes.util.find_library("mtp")
    if found:
        LIBMTP_PATH = found
    else:
        print("ERROR: libmtp not found. Install with: brew install libmtp", file=sys.stderr)
        sys.exit(1)

lib = ctypes.cdll.LoadLibrary(LIBMTP_PATH)

# ---------------------------------------------------------------------------
# Structs — must match libmtp.h exactly
# ---------------------------------------------------------------------------

class DeviceEntry(ctypes.Structure):
    _fields_ = [
        ("vendor", ctypes.c_char_p),
        ("vendor_id", ctypes.c_uint16),
        ("product", ctypes.c_char_p),
        ("product_id", ctypes.c_uint16),
        ("device_flags", ctypes.c_uint32),
    ]

class RawDevice(ctypes.Structure):
    _fields_ = [
        ("device_entry", DeviceEntry),
        ("bus_location", ctypes.c_uint32),
        ("devnum", ctypes.c_uint8),
    ]

class MtpDevice(ctypes.Structure):
    """Opaque — we only use pointers to this."""
    pass

class MtpFile(ctypes.Structure):
    pass

MtpFile._fields_ = [
    ("item_id", ctypes.c_uint32),
    ("parent_id", ctypes.c_uint32),
    ("storage_id", ctypes.c_uint32),
    ("filename", ctypes.c_char_p),
    ("filesize", ctypes.c_uint64),
    ("modificationdate", ctypes.c_long),
    ("filetype", ctypes.c_int),
    ("next", ctypes.POINTER(MtpFile)),
]

class MtpFolder(ctypes.Structure):
    pass

MtpFolder._fields_ = [
    ("folder_id", ctypes.c_uint32),
    ("parent_id", ctypes.c_uint32),
    ("storage_id", ctypes.c_uint32),
    ("name", ctypes.c_char_p),
    ("sibling", ctypes.POINTER(MtpFolder)),
    ("child", ctypes.POINTER(MtpFolder)),
]

# File type constants
FILETYPE_FOLDER = 0
FILETYPE_UNKNOWN = 44

# Storage ID (Kindle Scribe internal storage)
STORAGE_ID = 0x00010001

# ---------------------------------------------------------------------------
# Function signatures
# ---------------------------------------------------------------------------

lib.LIBMTP_Init()

lib.LIBMTP_Detect_Raw_Devices.restype = ctypes.c_int
lib.LIBMTP_Detect_Raw_Devices.argtypes = [
    ctypes.POINTER(ctypes.POINTER(RawDevice)),
    ctypes.POINTER(ctypes.c_int),
]

# Cached version — pre-loads file/folder tree on connect
lib.LIBMTP_Open_Raw_Device.restype = ctypes.POINTER(MtpDevice)
lib.LIBMTP_Open_Raw_Device.argtypes = [ctypes.POINTER(RawDevice)]

lib.LIBMTP_Release_Device.restype = None
lib.LIBMTP_Release_Device.argtypes = [ctypes.POINTER(MtpDevice)]

lib.LIBMTP_Get_Friendlyname.restype = ctypes.c_char_p
lib.LIBMTP_Get_Friendlyname.argtypes = [ctypes.POINTER(MtpDevice)]

# File listing (full device, uses cached data)
lib.LIBMTP_Get_Filelisting_With_Callback.restype = ctypes.POINTER(MtpFile)
lib.LIBMTP_Get_Filelisting_With_Callback.argtypes = [
    ctypes.POINTER(MtpDevice),
    ctypes.c_void_p,  # progress callback
    ctypes.c_void_p,  # callback data
]

# Files in a specific folder
lib.LIBMTP_Get_Files_And_Folders.restype = ctypes.POINTER(MtpFile)
lib.LIBMTP_Get_Files_And_Folders.argtypes = [
    ctypes.POINTER(MtpDevice),
    ctypes.c_uint32,  # storage_id
    ctypes.c_uint32,  # parent_id (0xFFFFFFFF for root)
]

# Folder tree
lib.LIBMTP_Get_Folder_List.restype = ctypes.POINTER(MtpFolder)
lib.LIBMTP_Get_Folder_List.argtypes = [ctypes.POINTER(MtpDevice)]

# Download file
lib.LIBMTP_Get_File_To_File.restype = ctypes.c_int
lib.LIBMTP_Get_File_To_File.argtypes = [
    ctypes.POINTER(MtpDevice),
    ctypes.c_uint32,   # file_id
    ctypes.c_char_p,   # output path
    ctypes.c_void_p,   # progress callback
    ctypes.c_void_p,   # callback data
]

# Upload file
lib.LIBMTP_Send_File_From_File.restype = ctypes.c_int
lib.LIBMTP_Send_File_From_File.argtypes = [
    ctypes.POINTER(MtpDevice),
    ctypes.c_char_p,          # local path
    ctypes.POINTER(MtpFile),  # file metadata (parent_id, filename, size, etc.)
    ctypes.c_void_p,          # progress callback
    ctypes.c_void_p,          # callback data
]

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def detect():
    """Check if an MTP device is connected. Returns (vendor, product) or None."""
    raw_devices = ctypes.POINTER(RawDevice)()
    num_devices = ctypes.c_int(0)

    ret = lib.LIBMTP_Detect_Raw_Devices(
        ctypes.byref(raw_devices), ctypes.byref(num_devices)
    )

    if ret != 0 or num_devices.value == 0:
        return None

    entry = raw_devices[0].device_entry
    vendor = entry.vendor.decode("utf-8", errors="replace") if entry.vendor else "Unknown"
    product = entry.product.decode("utf-8", errors="replace") if entry.product else "Unknown"
    return (vendor, product)


def connect(quiet=False):
    """Connect to the first MTP device found. Uses cached mode."""
    raw_devices = ctypes.POINTER(RawDevice)()
    num_devices = ctypes.c_int(0)

    ret = lib.LIBMTP_Detect_Raw_Devices(
        ctypes.byref(raw_devices), ctypes.byref(num_devices)
    )

    if ret != 0 or num_devices.value == 0:
        if not quiet:
            print("No MTP devices found.", file=sys.stderr)
        return None

    if not quiet:
        entry = raw_devices[0].device_entry
        product = entry.product.decode("utf-8", errors="replace") if entry.product else "device"
        print(f"Connecting to {product} (cached mode)...", file=sys.stderr)

    device = lib.LIBMTP_Open_Raw_Device(ctypes.byref(raw_devices[0]))

    if not device:
        if not quiet:
            print("Failed to open device.", file=sys.stderr)
        return None

    if not quiet:
        name = lib.LIBMTP_Get_Friendlyname(device)
        friendly = name.decode("utf-8", errors="replace") if name else "Unknown"
        print(f"Connected: {friendly}", file=sys.stderr)

    return device


def list_files(device, search=None):
    """List all files on the device. Returns list of dicts."""
    files_ptr = lib.LIBMTP_Get_Filelisting_With_Callback(device, None, None)

    results = []
    current = files_ptr
    while current:
        try:
            f = current.contents
        except ValueError:
            break
        name = f.filename.decode("utf-8", errors="replace") if f.filename else "(none)"
        results.append({
            "id": f.item_id,
            "parent_id": f.parent_id,
            "storage_id": f.storage_id,
            "name": name,
            "size": f.filesize,
            "type": f.filetype,
        })
        current = f.next

    if search:
        search_lower = search.lower()
        results = [r for r in results if search_lower in r["name"].lower()]

    return results


def list_folder_contents(device, storage_id, parent_id):
    """List files/folders in a specific folder."""
    files_ptr = lib.LIBMTP_Get_Files_And_Folders(
        device, ctypes.c_uint32(storage_id), ctypes.c_uint32(parent_id)
    )

    results = []
    current = files_ptr
    while current:
        try:
            f = current.contents
        except ValueError:
            break
        name = f.filename.decode("utf-8", errors="replace") if f.filename else "(none)"
        results.append({
            "id": f.item_id,
            "parent_id": f.parent_id,
            "storage_id": f.storage_id,
            "name": name,
            "size": f.filesize,
            "type": f.filetype,
        })
        current = f.next

    return results


def get_folder_tree(device):
    """Get the full folder tree. Returns nested dict structure."""
    folders_ptr = lib.LIBMTP_Get_Folder_List(device)

    def walk(folder_ptr, depth=0):
        results = []
        current = folder_ptr
        while current:
            try:
                f = current.contents
            except ValueError:
                break
            name = f.name.decode("utf-8", errors="replace") if f.name else "(none)"
            entry = {
                "id": f.folder_id,
                "parent_id": f.parent_id,
                "name": name,
                "children": walk(f.child, depth + 1),
            }
            results.append(entry)
            current = f.sibling
        return results

    return walk(folders_ptr)


def find_folder_by_name(tree, name):
    """Recursively search folder tree for a folder by name."""
    for folder in tree:
        if folder["name"] == name:
            return folder
        found = find_folder_by_name(folder["children"], name)
        if found:
            return found
    return None


def get_file(device, file_id, output_path):
    """Download a file from the device."""
    ret = lib.LIBMTP_Get_File_To_File(
        device,
        ctypes.c_uint32(file_id),
        output_path.encode("utf-8"),
        None,
        None,
    )
    return ret == 0


def send_file(device, local_path, parent_id, storage_id=STORAGE_ID, remote_name=None):
    """Upload a file to the device."""
    if not os.path.exists(local_path):
        print(f"ERROR: Local file not found: {local_path}", file=sys.stderr)
        return False

    if remote_name is None:
        remote_name = os.path.basename(local_path)

    file_size = os.path.getsize(local_path)

    # Create file metadata struct
    filedata = MtpFile()
    filedata.filename = remote_name.encode("utf-8")
    filedata.filesize = file_size
    filedata.filetype = FILETYPE_UNKNOWN
    filedata.parent_id = parent_id
    filedata.storage_id = storage_id

    ret = lib.LIBMTP_Send_File_From_File(
        device,
        local_path.encode("utf-8"),
        ctypes.byref(filedata),
        None,
        None,
    )
    return ret == 0


def print_folder_tree(tree, indent=0):
    """Print folder tree with indentation."""
    for folder in tree:
        print(f"{'  ' * indent}[{folder['id']}] {folder['name']}/")
        print_folder_tree(folder["children"], indent + 1)


def find_notebooks(device):
    """Find all notebook GUID folders and their nbk files.

    Uses cached folder tree + full file listing (both work in cached mode).
    Does NOT use Get_Files_And_Folders (which is incompatible with cached mode).

    Returns list of dicts:
        {"guid": str, "folder_id": int, "nbk_id": int, "nbk_size": int}
    """
    import re
    guid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE,
    )

    # Get folder tree and full file listing (both use cached data)
    tree = get_folder_tree(device)
    notebooks_folder = find_folder_by_name(tree, ".notebooks")

    if not notebooks_folder:
        print("WARNING: .notebooks folder not found in folder tree.", file=sys.stderr)
        return []

    # Build set of GUID folder IDs and their names
    guid_folders = {}  # folder_id -> guid
    for subfolder in notebooks_folder["children"]:
        if guid_pattern.match(subfolder["name"]):
            guid_folders[subfolder["id"]] = subfolder["name"]

    if not guid_folders:
        print("WARNING: No GUID folders found under .notebooks/", file=sys.stderr)
        return []

    # Get full file listing and find nbk files whose parent is a GUID folder
    all_files = list_files(device)
    results = []

    for f in all_files:
        if f["name"] == "nbk" and f["parent_id"] in guid_folders:
            guid = guid_folders[f["parent_id"]]
            results.append({
                "guid": guid,
                "folder_id": f["parent_id"],
                "nbk_id": f["id"],
                "nbk_size": f["size"],
            })

    return results


def pull_notebooks(device, output_dir):
    """Download all notebooks, skipping unchanged ones (SHA256 hash check).

    Returns list of dicts for notebooks that were downloaded (new or changed).
    """
    import hashlib

    os.makedirs(output_dir, exist_ok=True)
    hash_file = os.path.join(output_dir, ".nbk_hashes.json")

    # Load previous hashes
    prev_hashes = {}
    if os.path.exists(hash_file):
        with open(hash_file) as f:
            prev_hashes = json.load(f)

    notebooks = find_notebooks(device)
    if not notebooks:
        print("No notebooks found.", file=sys.stderr)
        return []

    print(f"Found {len(notebooks)} notebook(s).", file=sys.stderr)

    downloaded = []
    current_hashes = dict(prev_hashes)

    for nb in notebooks:
        guid = nb["guid"]
        guid_dir = os.path.join(output_dir, guid)
        os.makedirs(guid_dir, exist_ok=True)
        nbk_path = os.path.join(guid_dir, "nbk")

        print(f"  {guid} ({nb['nbk_size']:,} bytes)...", end=" ", file=sys.stderr)

        # Download to temp file first
        tmp_path = nbk_path + ".tmp"
        if not get_file(device, nb["nbk_id"], tmp_path):
            print("FAILED", file=sys.stderr)
            continue

        # Hash the downloaded file
        with open(tmp_path, "rb") as f:
            new_hash = hashlib.sha256(f.read()).hexdigest()

        if guid in prev_hashes and prev_hashes[guid] == new_hash:
            print("unchanged", file=sys.stderr)
            os.remove(tmp_path)
            continue

        # Move temp to final
        os.replace(tmp_path, nbk_path)
        current_hashes[guid] = new_hash
        downloaded.append({"guid": guid, "path": nbk_path, "size": nb["nbk_size"]})
        print("downloaded", file=sys.stderr)

    # Save hashes
    with open(hash_file, "w") as f:
        json.dump(current_hashes, f, indent=2)

    return downloaded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Kindle Scribe MTP file access (persistent connection)"
    )
    parser.add_argument("--detect", action="store_true",
                        help="Check if device is connected (exit 0=yes, 1=no)")
    parser.add_argument("--list", action="store_true",
                        help="List all files on device")
    parser.add_argument("--search", type=str,
                        help="Search filenames (case-insensitive)")
    parser.add_argument("--folders", action="store_true",
                        help="Show folder tree")
    parser.add_argument("--get", nargs=2, metavar=("FILE_ID", "OUTPUT"),
                        help="Download a file by ID")
    parser.add_argument("--get-many", nargs="+", metavar="ID:OUTPUT",
                        help="Download multiple files (ID:path pairs)")
    parser.add_argument("--send", nargs=2, metavar=("LOCAL_PATH", "PARENT_ID"),
                        help="Upload a file to a folder on the device")
    parser.add_argument("--notebooks", action="store_true",
                        help="List notebook GUID folders and their nbk files")
    parser.add_argument("--pull-notebooks", type=str, metavar="OUTPUT_DIR",
                        help="Download all changed notebooks to OUTPUT_DIR")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON (for scripting)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress status messages")
    args = parser.parse_args()

    # --detect is special: just check and exit
    if args.detect:
        result = detect()
        if result:
            if args.json:
                print(json.dumps({"connected": True, "vendor": result[0], "product": result[1]}))
            else:
                print(f"{result[0]} {result[1]}")
            sys.exit(0)
        else:
            if args.json:
                print(json.dumps({"connected": False}))
            else:
                print("No device found", file=sys.stderr)
            sys.exit(1)

    # All other commands need a full connection
    device = connect(quiet=args.quiet)
    if not device:
        sys.exit(1)

    try:
        if args.list or args.search:
            results = list_files(device, search=args.search)
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                for r in results:
                    print(f"  ID={r['id']:6d}  parent={r['parent_id']:6d}  "
                          f"size={r['size']:>12,}  {r['name']}")
                print(f"\n{len(results)} file(s)", file=sys.stderr)

        elif args.folders:
            tree = get_folder_tree(device)
            if args.json:
                print(json.dumps(tree, indent=2))
            else:
                print_folder_tree(tree)

        elif args.get:
            file_id = int(args.get[0])
            output = args.get[1]
            if not args.quiet:
                print(f"Downloading file ID {file_id} -> {output}", file=sys.stderr)
            if get_file(device, file_id, output):
                size = os.path.getsize(output)
                if not args.quiet:
                    print(f"Success: {size:,} bytes", file=sys.stderr)
                if args.json:
                    print(json.dumps({"success": True, "size": size, "path": output}))
            else:
                print(f"ERROR: Download failed for ID {file_id}", file=sys.stderr)
                sys.exit(1)

        elif args.get_many:
            results = []
            for pair in args.get_many:
                file_id_str, output = pair.split(":", 1)
                file_id = int(file_id_str)
                if not args.quiet:
                    print(f"Downloading file ID {file_id} -> {output}", file=sys.stderr)
                ok = get_file(device, file_id, output)
                size = os.path.getsize(output) if ok else 0
                results.append({"id": file_id, "success": ok, "size": size, "path": output})
                if not args.quiet:
                    status = f"{size:,} bytes" if ok else "FAILED"
                    print(f"  {status}", file=sys.stderr)
            if args.json:
                print(json.dumps(results, indent=2))

        elif args.send:
            local_path = args.send[0]
            parent_id = int(args.send[1])
            if not args.quiet:
                print(f"Uploading {local_path} -> parent {parent_id}", file=sys.stderr)
            if send_file(device, local_path, parent_id):
                if not args.quiet:
                    print("Upload successful", file=sys.stderr)
                if args.json:
                    print(json.dumps({"success": True}))
            else:
                print("ERROR: Upload failed", file=sys.stderr)
                sys.exit(1)

        elif args.notebooks:
            notebooks = find_notebooks(device)
            if args.json:
                print(json.dumps(notebooks, indent=2))
            else:
                for nb in notebooks:
                    print(f"  {nb['guid']}  nbk_id={nb['nbk_id']}  "
                          f"size={nb['nbk_size']:>12,}")
                print(f"\n{len(notebooks)} notebook(s)", file=sys.stderr)

        elif args.pull_notebooks:
            downloaded = pull_notebooks(device, args.pull_notebooks)
            if args.json:
                print(json.dumps(downloaded, indent=2))
            else:
                if downloaded:
                    print(f"\nDownloaded {len(downloaded)} notebook(s):", file=sys.stderr)
                    for d in downloaded:
                        print(f"  {d['guid']} ({d['size']:,} bytes)", file=sys.stderr)
                else:
                    print("All notebooks up to date.", file=sys.stderr)

        else:
            parser.print_help()

    finally:
        lib.LIBMTP_Release_Device(device)

    sys.exit(0)


if __name__ == "__main__":
    main()
