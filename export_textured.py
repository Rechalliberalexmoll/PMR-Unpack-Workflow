#!/usr/bin/env python3
"""Export one vehicle with textures: OBJ (v/vn/vt) + MTL + texture PNGs.

Chain: Shape.materialIds -> Material node -> Custommap albedo -> File path.
Textures/Liveries DDS are converted to PNG alongside the OBJ.
"""
import struct
import sys
import re
import time
from pathlib import Path
from xml.etree import ElementTree as ET
from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "blender_ref"))
import i3d_shapes_reader as R

UV_FLAGS = (0x02, 0x04, 0x08, 0x10)
VEHICLES = Path(r"G:\Games\Project Motor Racing\data\vehicles")
OUT = Path(r"D:\Games\model output\PMR output")
LOD_LEVEL = {"A": 4, "B": 3, "C": 2, "D": 1}


def read_entities(path):
    with open(path, "rb") as f:
        raw = f.read()
    header = R.FileHeader.read(__import__("io").BytesIO(raw))
    cipher = R.I3DCipher(header.seed)
    reader = R.CipherBinReader(raw[4:], cipher, little_endian=header.version >= 4)
    count = reader.read_int32()
    ents = []
    for _ in range(count):
        t = reader.read_int32()
        sz = reader.read_int32()
        ents.append(R.RawEntity(t, reader.read_bytes(sz)))
    return header, ents


def parse_xml(i3d_path):
    """Return (shape_map, file_map, mat_map).
    shape_map: shapeId -> (name, [materialIds])
    file_map:  fileId -> relative png path (e.g. textures/t_x.png)
    mat_map:   materialId -> (mat_name, albedo_fileId)
    """
    tree = ET.parse(i3d_path)
    root = tree.getroot()
    file_map = {}
    for node in root.iter("File"):
        fid = node.get("fileId")
        fn = node.get("filename", "")
        if not fid:
            continue
        # shared dirs (_common_textures/_tires/_brakes/_Safety_Nets) -> _shared/
        if re.search(r"/vehicles/_[^/]+/", fn, re.I):
            m2 = re.search(r"/([^/]+)\.(png|dds)$", fn, re.I)
            if m2:
                file_map[int(fid)] = f"_shared/{m2.group(1)}.png"
            continue
        # $data/vehicles/<dir>/Textures/x.png -> textures/x.png
        m = re.search(r"/(Textures|Liveries)/([^/]+)\.(png|dds)$", fn, re.I)
        if m:
            sub = "textures" if m.group(1).lower() == "textures" else "liveries"
            file_map[int(fid)] = f"{sub}/{m.group(2)}.png"
    mat_map = {}
    for node in root.iter("Material"):
        mid = node.get("materialId")
        mname = node.get("name", f"mat_{mid}")
        cands = []
        for cm in node.iter("Custommap"):
            cname = cm.get("name", "")
            fid = cm.get("fileId")
            if fid and re.search(r"albedo|base_?color", cname, re.I):
                cands.append((int(fid), file_map.get(int(fid), "")))
        png = None
        used_blacklist = False
        for fid, rel in cands:
            if "t_common_paint_alb" in rel:
                used_blacklist = True
                continue
            png = rel
            break
        if used_blacklist:
            # test-UV swatch was skipped: prefer the car's real livery
            liv = Path(i3d_path).parent / "Liveries"
            if liv.exists():
                for pat in ("*factory*livery*alb*.dds", "*livery*alb*.dds"):
                    for dds in sorted(liv.glob(pat)):
                        if "t_common_paint_alb" in dds.name:
                            continue
                        png = f"liveries/{dds.stem}.png"
                        break
                    if png:
                        break
        if mid:
            mat_map[int(mid)] = (mname, png)
    shape_map = {}
    xforms = {}

    def parse_tf(el):
        M = np.eye(4)
        tr = el.get("translation")
        if tr:
            x, y, z = map(float, tr.split())
            M[:3, 3] = (x, y, z)
        rot = el.get("rotation")
        if rot:
            rx, ry, rz = map(float, rot.split())
            rx, ry, rz = np.radians([rx, ry, rz])
            cx, sx = np.cos(rx), np.sin(rx)
            cy, sy = np.cos(ry), np.sin(ry)
            cz, sz = np.cos(rz), np.sin(rz)
            Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
            Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
            Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
            M[:3, :3] = Rz @ Ry @ Rx
        sc = el.get("scale")
        if sc:
            sx, sy, sz = map(float, sc.split())
            M[:3, 0] *= sx
            M[:3, 1] *= sy
            M[:3, 2] *= sz
        return M

    def walk(el, parent):
        M = parent
        if el.tag == "TransformGroup":
            M = parent @ parse_tf(el)
        elif el.tag == "Shape":
            M = parent @ parse_tf(el)  # Shape node may carry its own transform
            sid = el.get("shapeId")
            nm = el.get("name")
            mids = [int(x) for x in (el.get("materialIds") or "").split(",") if x.strip()]
            if sid and nm:
                shape_map[int(sid)] = (nm, mids)
                xforms[int(sid)] = M
        for child in el:
            walk(child, M)

    walk(root, np.eye(4))
    return shape_map, file_map, mat_map, xforms


def entity_id(data):
    nl = struct.unpack_from("<i", data, 0)[0]
    pos = 4 + nl
    pos = (pos + 3) & ~3
    return struct.unpack_from("<I", data, pos)[0]


def parse(data):
    nl = struct.unpack_from("<i", data, 0)[0]
    raw_name = data[4 : 4 + nl].decode("ascii", "replace")
    pos = 4 + nl
    pos = (pos + 3) & ~3
    pos += 4
    pos += 16  # bv
    corner, nsub, nvert, opts = struct.unpack_from("<IIII", data, pos)
    pos += 16
    pos += 4  # vtxCompression
    pos += 4  # extra 4B

    # subsets
    n_dens = sum(1 for f in UV_FLAGS if opts & f)
    subsets = []
    sp = pos
    for _ in range(nsub):
        fv, nv, fi, ni = struct.unpack_from("<IIII", data, sp)
        sp += 16 + n_dens * 4
        subsets.append((fv, nv, fi, ni))
    sub_end = sp
    T = (sub_end + nsub * 2 + 3) & ~3

    ntri = corner // 3
    is_int = nvert > 0xFFFF + 1
    ic = "I" if is_int else "H"
    isz = 4 if is_int else 2
    ii = list(struct.unpack_from(f"<{ntri*3}{ic}", data, T))
    if max(ii) >= nvert:
        raise ValueError(f"index overflow {raw_name}")
    po = T + ntri * 3 * isz
    po = (po + 3) & ~3
    pv = struct.unpack_from(f"<{nvert*3}f", data, po)

    p2 = po + nvert * 12
    normals = None
    if opts & 0x01:
        nv = struct.unpack_from(f"<{nvert*3}f", data, p2)
        normals = [(nv[i], nv[i + 1], nv[i + 2]) for i in range(0, len(nv), 3)]
        p2 += nvert * 12
    if opts & 0x80:
        p2 += nvert * 16  # tangents
    uvs = None
    if opts & 0x02:  # UV1
        uv = struct.unpack_from(f"<{nvert*2}f", data, p2)
        uvs = [(uv[i], uv[i + 1]) for i in range(0, len(uv), 2)]

    xs = pv[0::3]; ys = pv[1::3]; zs = pv[2::3]
    mn = (min(xs), min(ys), min(zs)); mx = (max(xs), max(ys), max(zs))
    cx = (mn[0] + mx[0]) / 2; cy = (mn[1] + mx[1]) / 2; cz = (mn[2] + mx[2]) / 2
    r = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) / 2
    a, b, c, d = struct.unpack_from("<4f", data, ((4 + nl + 3) & ~3) + 4)
    err = abs(a - cx) + abs(b - cy) + abs(c - cz) + abs(d - r)
    rel_err = err / max(abs(d), 1e-6)

    tris = [(ii[i] + 1, ii[i + 1] + 1, ii[i + 2] + 1) for i in range(0, len(ii), 3)]
    positions = [(pv[i], pv[i + 1], pv[i + 2]) for i in range(0, len(pv), 3)]
    return raw_name, positions, normals, uvs, tris, subsets, rel_err


def lod_level(name):
    m = re.search(r"_LOD([A-D])$", name, re.I)
    return LOD_LEVEL[m.group(1).upper()] if m else None


def best_level_only(parts):
    best = {}
    for item in parts:
        name = item[0]
        lv = lod_level(name)
        base = re.sub(r"_LOD[A-D]$", "", name, flags=re.I)
        cur = best.get(base)
        if cur is None or (lv or 0) > (cur[0] or 0):
            best[base] = (lv, item)
    return [item for _, item in best.values()]


def convert_textures(src_dir, out_sub):
    """Convert all DDS in src_dir to PNG under out_sub. Returns count."""
    out_sub.mkdir(parents=True, exist_ok=True)
    n = 0
    for dds in src_dir.glob("*.dds"):
        png = out_sub / (dds.stem + ".png")
        if png.exists() and png.stat().st_size > 0:
            n += 1
            continue
        try:
            im = Image.open(dds)
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGBA")
            im.save(png)
            n += 1
        except Exception as ex:
            print(f"    [WARN] texture {dds.name}: {ex}")
    return n


LOD_EXCLUDE = re.compile(r"INTERIOR|STEERINGWHEEL|SWHEEL", re.I)  # drop from exterior (kept in CPIT/SWHEEL file)
CPIT_INCLUDE = re.compile(r"INTANIM|INTERIOR|STEERINGWHEEL|SWHEEL|MIRROR_C", re.I)  # cockpit parts to keep


def load_parts(src, i3d, name_filter=None, exclude=False):
    """Parse one shapes file -> (parts, mat_defs).
    name_filter: regex; exclude=False keeps matches, exclude=True drops them.
    part = (name, positions, normals, uvs, tris, subsets, [material names], rel_err)
    mat_defs: mname -> png relative path or None
    """
    header, ents = read_entities(str(src))
    if header.version not in (10, 11, 12):
        raise ValueError(f"unsupported shapes version {header.version}")
    shape_map, file_map, mat_map, xforms = parse_xml(i3d)
    parts = []
    for e in ents:
        if e.entity_type.name != "SHAPE":
            continue
        try:
            raw_name, pos, norm, uvs, tris, subsets, rel_err = parse(e.data)
            eid = entity_id(e.data)
            xml_name, mids = shape_map.get(eid, (raw_name, []))
            # GIANTS exporter bugs: entity name with .001 suffix -> XML name is
            # authoritative (wing stored as BODY_*.001); otherwise entity name is
            # authoritative (XML wrongly renames WHEEL_LF_* to WHEEL_LR_*).
            if re.search(r"\.\d+$", raw_name):
                name = xml_name
            else:
                name = raw_name
            if re.search(r"BLUR", name, re.I):
                continue
            if name_filter:
                hit = bool(name_filter.search(name))
                if (exclude and hit) or (not exclude and not hit):
                    continue
            M = xforms.get(eid)
            if M is not None:
                P = np.array(pos, dtype=np.float64)
                P = P @ M[:3, :3].T + M[:3, 3]
                pos = [tuple(p) for p in P]
                if norm is not None:
                    N = np.linalg.inv(M[:3, :3]).T
                    Nn = np.array(norm, dtype=np.float64) @ N.T
                    ln = np.linalg.norm(Nn, axis=1, keepdims=True)
                    ln[ln == 0] = 1.0
                    Nn = Nn / ln
                    norm = [tuple(n) for n in Nn]
            mnames = [mat_map[mid][0] if mid in mat_map else None for mid in mids]
            parts.append((name, pos, norm, uvs, tris, subsets, mnames, rel_err))
        except Exception as ex:
            print(f"    [WARN] parse failed: {ex}")
    parts = best_level_only(parts)
    mat_defs = {}
    for name, pos, norm, uvs, tris, subsets, mnames, rel_err in parts:
        for mn in mnames:
            if mn and mn not in mat_defs:
                for mid, (mname, png) in mat_map.items():
                    if mname == mn:
                        mat_defs[mn] = png
                        break
                else:
                    mat_defs[mn] = None
    return parts, mat_defs


def write_obj(all_parts, all_mat_defs, out_obj):
    """Write merged OBJ + MTL. Materials deduped by name across sources."""
    mat_defs = {}
    for md in all_mat_defs:
        for mn, png in md.items():
            if mn not in mat_defs:
                mat_defs[mn] = png

    out_obj.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = out_obj.with_suffix(".mtl")
    with mtl_path.open("w", encoding="utf-8", newline="\n") as fm:
        fm.write("# Project Motor Racing vehicle materials\n")
        for mn in sorted(mat_defs):
            fm.write(f"\nnewmtl {mn}\n")
            fm.write("Kd 1.000 1.000 1.000\nKa 0.000 0.000 0.000\nKs 0.200 0.200 0.200\nNs 32\n")
            png = mat_defs[mn]
            if png:
                fm.write(f"map_Kd {png}\n")

    vo = 0
    to = 0
    with out_obj.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"mtllib {mtl_path.name}\n")
        for name, pos, norm, uvs, tris, subsets, mnames, rel_err in all_parts:
            f.write(f"g {name}\n")
            for p in pos:
                f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
            if norm:
                for n in norm:
                    f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
            if uvs:
                for t in uvs:
                    f.write(f"vt {t[0]:.6f} {t[1]:.6f}\n")
            if subsets and uvs and norm:
                for si, (fv, nv_, fi, ni) in enumerate(subsets):
                    mname = mnames[si] if si < len(mnames) else None
                    if mname:
                        f.write(f"usemtl {mname}\n")
                    end = fi + ni
                    for ti in range(fi // 3, end // 3):
                        if ti >= len(tris):
                            break
                        a, b, c = tris[ti]
                        f.write(f"f {a+vo}/{a+to}/{a+vo} {b+vo}/{b+to}/{b+vo} {c+vo}/{c+to}/{c+vo}\n")
            else:
                for t in tris:
                    a, b, c = t
                    if uvs and norm:
                        f.write(f"f {a+vo}/{a+to}/{a+vo} {b+vo}/{b+to}/{b+vo} {c+vo}/{c+to}/{c+vo}\n")
                    elif norm:
                        f.write(f"f {a+vo}//{a+vo} {b+vo}//{b+vo} {c+vo}//{c+vo}\n")
                    else:
                        f.write(f"f {a+vo} {b+vo} {c+vo}\n")
            vo += len(pos)
            to += len(uvs) if uvs else 0

    tv = sum(len(p[1]) for p in all_parts)
    tt = sum(len(p[4]) for p in all_parts)
    shared = []
    for mn, png in mat_defs.items():
        if png and png.startswith("_shared/"):
            stem = Path(png).stem
            for sub in ("_common_textures", "_tires", "_brakes"):
                dds = VEHICLES / sub / (stem + ".dds")
                if dds.exists():
                    shared.append((dds, out_obj.parent / png))
                    break
    return len(all_parts), tv, tt, shared


def export_one(src, i3d, out_obj):
    parts, mat_defs = load_parts(src, i3d)
    ok, tv, tt, shared = write_obj(parts, [mat_defs], out_obj)
    bad = [(p[0], round(p[7], 3)) for p in parts if p[7] > 0.3]
    nuv = sum(1 for p in parts if p[3])
    return ok, tv, tt, nuv, bad, shared


def export_merged(lod_src, cpid_src, lod_i3d, cpid_i3d, out_obj, swheel_src=None, swheel_i3d=None):
    lod_parts, lod_mats = load_parts(lod_src, lod_i3d, name_filter=LOD_EXCLUDE, exclude=True)
    cpid_parts, cpid_mats = load_parts(cpid_src, cpid_i3d, name_filter=CPIT_INCLUDE)
    all_parts = lod_parts + cpid_parts
    all_mats = [lod_mats, cpid_mats]
    n_sw = 0
    if swheel_src is not None:
        sw_parts, sw_mats = load_parts(swheel_src, swheel_i3d)  # steering-wheel file: keep all
        all_parts += sw_parts
        all_mats.append(sw_mats)
        n_sw = len(sw_parts)
    ok, tv, tt, shared = write_obj(all_parts, all_mats, out_obj)
    bad = [(p[0], round(p[7], 3)) for p in all_parts if p[7] > 0.3]
    return ok, tv, tt, bad, shared, len(lod_parts), len(cpid_parts), n_sw


def collect_vehicle_dirs():
    """Base game vehicles + unpacked DLC vehicles (dlcS_full / dataS_full)."""
    dirs = []
    seen = set()
    def add(d):
        if d.is_dir() and not d.name.startswith("_") and str(d) not in seen:
            seen.add(str(d))
            dirs.append(d)
    for d in sorted(VEHICLES.iterdir()):
        add(d)
    export_root = Path(r"G:\Games\Project Motor Racing\_export")
    for sub in ("dlcS_full", "dataS_full"):
        root = export_root / sub
        if not root.exists():
            continue
        for vroot in sorted(root.rglob("vehicles")):
            if vroot.is_dir():
                for d in sorted(vroot.iterdir()):
                    add(d)
    return dirs


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("--all", "--dlc"):
        dirs = [VEHICLES / sys.argv[1]]
    elif len(sys.argv) > 1 and sys.argv[1] == "--dlc":
        export_root = Path(r"G:\Games\Project Motor Racing\_export")
        dirs = []
        seen = set()
        for sub in ("dlcS_full", "dataS_full"):
            root = export_root / sub
            if not root.exists():
                continue
            for vroot in sorted(root.rglob("vehicles")):
                if vroot.is_dir():
                    for d in sorted(vroot.iterdir()):
                        if d.is_dir() and not d.name.startswith("_") and str(d) not in seen:
                            seen.add(str(d))
                            dirs.append(d)
    else:
        dirs = collect_vehicle_dirs()
    results = []
    t_all = time.time()
    for d in dirs:
        if not d.exists():
            print(f"not found: {d}")
            continue
        # multi-word brands (dir prefix contains extra underscores)
        multi = next((b for b in ("Aston_Martin",) if d.name.startswith(b + "_")), None)
        if multi:
            make = multi.replace("_", " ")
            model = d.name[len(multi) + 1 :]
        else:
            make = d.name.split("_")[0]
            model = d.name[len(make) + 1 :] or d.name
        shapes = sorted(
            [s for s in d.glob("*.i3d.shapes") if re.search(r"_(LOD|CPIT|SWHEEL)\.i3d\.shapes$", s.name, re.I)],
            key=lambda p: p.name.lower(),
        )
        if not shapes:
            print(f"[SKIP] {d.name}: no LOD shapes")
            continue
        out_dir = OUT / make / model
        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        tex_n = convert_textures(d / "Textures", out_dir / "textures") if (d / "Textures").exists() else 0
        liv_n = convert_textures(d / "Liveries", out_dir / "liveries") if (d / "Liveries").exists() else 0
        # exterior (LOD) + cockpit interior (CPIT) + steering wheel (SWHEEL) -> merged single OBJ
        lod_files = [s for s in shapes if re.search(r"_LOD\.i3d\.shapes$", s.name, re.I)]
        cpid_files = [s for s in shapes if re.search(r"_CPIT\.i3d\.shapes$", s.name, re.I)]
        swheel_files = [s for s in shapes if re.search(r"_SWHEEL\.i3d\.shapes$", s.name, re.I)]
        jobs = []
        if lod_files and cpid_files:
            jobs.append(("merged", lod_files[0], cpid_files[0], swheel_files[0] if swheel_files else None))
        else:
            for s in lod_files + cpid_files + swheel_files:
                jobs.append(("single", s, None, None))
        for kind, src, src2, src3 in jobs:
            i3d = Path(str(src).replace(".i3d.shapes", ".i3d"))
            base = re.sub(r"\.i3d\.shapes$", "", src.name, flags=re.I)
            if kind == "merged":
                out_obj = out_dir / f"{base}_merged_textured.obj"
            else:
                suffix = "_LODA_textured.obj" if re.search(r"_LOD\.", src.name, re.I) else "_textured.obj"
                out_obj = out_dir / f"{base}{suffix}"
            t = time.time()
            try:
                if kind == "merged":
                    i3d2 = Path(str(src2).replace(".i3d.shapes", ".i3d"))
                    i3d3 = Path(str(src3).replace(".i3d.shapes", ".i3d")) if src3 else None
                    ok, tv, tt, bad, shared, n_lod, n_cpit, n_sw = export_merged(
                        src, src2, i3d, i3d2, out_obj, swheel_src=src3, swheel_i3d=i3d3)
                    nuv = n_lod + n_cpit + n_sw
                    status = f"{ok}parts(lod={n_lod}+cpit={n_cpit}+sw={n_sw})/{tv}v/{tt}t"
                else:
                    ok, tv, tt, nuv, bad, shared = export_one(src, i3d, out_obj)
                    status = f"{ok}parts/{tv}v/{tt}t"
                for dds, png in shared:
                    png.parent.mkdir(parents=True, exist_ok=True)
                    if png.exists() and png.stat().st_size > 0:
                        continue
                    try:
                        im = Image.open(dds)
                        if im.mode not in ("RGB", "RGBA", "L"):
                            im = im.convert("RGBA")
                        im.save(png)
                    except Exception as ex:
                        print(f"    [WARN] shared {dds.name}: {ex}")
                # fallback: any map_Kd png missing on disk -> search shared/car dirs
                mtl_path = out_obj.with_suffix(".mtl")
                if mtl_path.exists():
                    for line in mtl_path.read_text(encoding="utf-8").splitlines():
                        m = re.match(r"map_Kd (.+)$", line)
                        if not m:
                            continue
                        rel = m.group(1)
                        pngp = out_obj.parent / rel
                        if pngp.exists():
                            continue
                        stem = Path(rel).stem
                        cands = [VEHICLES / s / (stem + ".dds") for s in ("_common_textures", "_tires", "_brakes")]
                        cands += [VEHICLES / "_Safety_Nets" / "Textures" / (stem + ".dds")]
                        cands += [d / "Textures" / (stem + ".dds"), d / "Liveries" / (stem + ".dds")]
                        for dds in cands:
                            if dds.exists():
                                pngp.parent.mkdir(parents=True, exist_ok=True)
                                try:
                                    im = Image.open(dds)
                                    if im.mode not in ("RGB", "RGBA", "L"):
                                        im = im.convert("RGBA")
                                    im.save(pngp)
                                    print(f"  fallback tex: {dds.name} -> {rel}")
                                except Exception as ex:
                                    print(f"    [WARN] {dds.name}: {ex}")
                                break
                        else:
                            print(f"  [WARN] texture not found: {rel}")
                if bad:
                    status += f" BVbad={len(bad)}"
                results.append((d.name, "OK", status))
                print(f"[OK] {d.name}: {src.name} -> {out_obj.name} {status} "
                      f"(tex={tex_n} liv={liv_n}, {time.time()-t:.1f}s)")
            except Exception as ex:
                results.append((d.name, "FAIL", str(ex)))
                print(f"[FAIL] {d.name}: {ex}")
        print(f"== {d.name}: done in {time.time()-t0:.1f}s")
    print(f"\n===== ALL DONE: {len(results)} cars in {time.time()-t_all:.1f}s =====")
    fails = [r for r in results if r[1] != "OK"]
    print(f"ok={len(results)-len(fails)} fail={len(fails)}")
    for r in fails:
        print(f"  FAIL {r[0]}: {r[2]}")


if __name__ == "__main__":
    sys.exit(main())
