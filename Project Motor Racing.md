# Project Motor Racing — 车辆模型导出流程

**完成日期：** 2026-01-19（基础车 71 辆 + DLC 车 52 辆，共 123 辆）
**输出根目录：** `D:\Games\model output\PMR output`
**最终产物：** `<车厂>\<车型>\*_merged_textured.obj`（外观 LODA + CPIT 内饰 + SWHEEL 方向盘 合并单 OBJ，带 MTL 贴图）
**游戏页：** [[project motor racing/Project Motor Racing|Project Motor Racing]]
**工具目录：** `D:\Games\Tools\I3DShapesTool\`（导出脚本 + i3d.shapes 逆向）
**GAR 解包工具：** `D:\Games\Tools\fs-utils-src\target\release\fs-unpack.exe`（scfmod/fs-utils 本地修复版）

---

## 1. 输入

| 项 | 路径 |
|----|------|
| 游戏 | `G:\Games\Project Motor Racing`（v2.3.0.3，GIANTS Engine 10） |
| 基础车 | `data\vehicles\<车>\`（71 辆） |
| DLC 归档 | `dlcS.gar`（22.5GB，41 辆 DLC 车）+ `dataS.gar`（4.8GB，12 辆车） |
| 模型二进制 | `*_LOD.i3d.shapes` 外观 / `*_CPIT.i3d.shapes` 座舱 / `*_SWHEEL.i3d.shapes` 方向盘 |
| 场景/材质 | `*.i3d` XML（权威部件名、材质链、场景树变换） |
| 贴图 | 车 `Textures\` `Liveries\`（DDS）+ 共享 `_common_textures` `_tires` `_brakes` `_Safety_Nets` |
| 输出 | `D:\Games\model output\PMR output\<车厂>\<车型>\` |

---

## 2. 流程（可复现）

### Step 1 — 解包 GAR 归档（DLC 车必需）

**工具：** fs-utils（`scfmod/fs-utils`）本地修复版，Rust nightly + MinGW 编译。

**关键发现（勿回归）：** GAR 文件表中 **flags=0x0 的条目（shapes/DDS/anim）是明文存储，不需要 GarCipher 解密**。原版 gar-lib 对所有条目 decrypt 导致这些文件乱码（DDS 头变 `40 05 56 34`、shapes version 乱值如 92/76）。修复：flags==0 直接复制原始字节。

```text
fs-unpack.exe <gar> <output_dir>        # 提取全部条目（含 flags=0）
fs-unpack.exe --list <gar> NUL          # 仅列表（name offset size xsize flags）
```

**解包结果：**
- `dlcS.gar` → 8271 文件 / 22.45GB（`_export\dlcS_full\`，含 s1_dlc1~5 + dlc_liveries）
- `dataS.gar` → 7505 文件 / 4.72GB（`_export\dataS_full\`，含 12 辆额外车）
- 合计 651+70 个 `.i3d.shapes`、5000+ DDS

**GAR 格式要点：** magic `GAR `@0x60；文件表@0x200（每项512B，GarCipher=DES变体+RC4，34块循环）；num_files=0x68+0x6C（version≥3）；flags@0、xsize@8、size@16、offset@24、name@0x28；密钥 KEYS_FS15_25=(0x30D0D6B6,0x14B281C4,0x2F28AC14,0x29F53CB9)（gar-lib tables.rs）。

### Step 2 — 解析 i3d XML（权威元数据）

- `shapeId → Shape name`：**必须用 XML 名**（GIANTS 导出器会存错名，如尾翼→`BODY_*.001`）
- `materialId → Material → Custommap(albedo) → File`：材质贴图链
- 场景树变换：`TransformGroup` 嵌套（translation/rotation度/scale）+ `Shape` 自身属性，累积 4×4 矩阵；法线用 3×3 逆转置

### Step 3 — 解析 v12 `.i3d.shapes` 二进制

```
name(i32+align4) → id(u32) → BoundingVolume(4f32) → corner → nsub → nvert → opts
→ vtxCompression(f32) → 4B extra(0)
→ subsets: nsub × [fv,nv,fi,ni + f32×popcount(opts&0x1E)]
→ 材质名区: nsub × u16(len,全0) + align4
→ 三角形索引(u16; nvert>65536 用 u32) → align4
→ positions → normals → tangents → UV1-4 → 顶点色 → 0x400段(nvert×32B) → ...
```

- 解密：I3DCipher（`blender_ref\i3d_shapes_reader.py` numpy 版）
- 校验：头部 `BoundingVolume=(cx,cy,cz,r)` 包围球 vs 解析顶点 bbox（相对误差 <0.3）

### Step 4 — 部件过滤（用户确认规则）

| 来源 | 规则 |
|------|------|
| LOD 外观 | 排除 `INTERIOR` `STEERINGWHEEL` `SWHEEL` `BLUR`；同基名只留最高级（LODA 优先，剥 `.001` 后缀合并） |
| CPIT 内饰 | 保留 `INTANIM` `INTERIOR` `STEERINGWHEEL` `SWHEEL` `MIRROR_C` |
| SWHEEL 文件 | 存在则全量并入（部分车方向盘独立存放） |

### Step 5 — 写合并 OBJ + MTL

- 顶点/法线/UV1 应用世界变换；`g <部件名>` 分组；按 subset 范围写 `usemtl` + `f v/vt/vn`
- MTL 材质按名去重，`map_Kd` 指向相对路径 PNG

### Step 6 — 贴图转换（Pillow DDS→PNG）

- 车 `Textures\`/`Liveries\` 全量转 PNG
- **黑名单 `t_common_paint_alb`**（测试 UV 贴图）→ 回退车 `Liveries\` 工厂涂装（`*factory*livery*alb*` 优先）
- 共享目录贴图 → `_shared\`；车目录缺失时全目录回退搜索（`_Safety_Nets` 等）

---

## 3. 命令

```text
# 单车（车目录名）
python export_textured.py Toyota_Supra_GT4

# 全部基础车 + DLC 车（约 25 分钟）
python export_textured.py --all

# 仅 DLC 车（dlcS_full + dataS_full，约 15 分钟）
python export_textured.py --dlc
```

脚本：`D:\Games\Tools\I3DShapesTool\export_textured.py`
依赖：MIMO_PYTHON（numpy + Pillow），`blender_ref\i3d_shapes_reader.py`

---

## 4. 结果与校验

| 指标 | 数值 |
|------|------|
| 车辆 | **123/123**（71 基础 + 52 DLC），0 失败 |
| 部件 | 4,323（每车 = 外观 LODA + CPIT 内饰 + SWHEEL） |
| 贴图 | 3,261 处 map_Kd，0 缺失；10,333 个 PNG |
| 体积 | 11.64 GB / 10,579 文件 |

单车验证项：BV 相对误差、blur=0、方向盘唯一、map_Kd 完整、轮子/刹车/方向盘位置与场景树节点吻合。

---

## 5. 已修问题（勿回归）

1. 子集大小 = `16 + popcount(opts&0x1E)×4`（曾按固定 32 算 → 少 UV 部件错位）
2. subsets 后**材质名区**（nsub×u16 + align4）曾漏 → 多 subset 部件三角形整体错位
3. `.001` 重名件是**不同部件**（尾翼等），按 XML 权威名分组，勿按基名误合并
4. Shape 节点**自带 rotation**（如 M4 的 `-0 -90 0`）必须应用；轮胎靠 Shape 自身 transform 装到轮位
5. LOD/CPIT 双份内饰要去重；方向盘命名变体（`SWHEEL` vs `STEERINGWHEEL`）
6. 测试涂装 `t_common_paint_alb` 黑名单
7. Blender 4.2 导入用 `bpy.ops.wm.obj_import`（`wavefront.obj.import` 会语法错误）
8. **GAR flags=0 条目是明文**（shapes/DDS），不能 decrypt——否则 shapes version 乱值、DDS 头变 `40 05 56 34`
9. 多词品牌（`Aston_Martin_*`）目录拆分要特判

---

## 6. 待办

- DLC 贴图如遇 Pillow 无法识别的特殊格式，逐车排查（当前 3261 处 map_Kd 全部有效）
- CPIT/DISPLAY 等其余文件类型按需扩展（当前合并 LOD+CPIT+SWHEEL）
