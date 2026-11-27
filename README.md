# PMR-Unpack-Workflow

Project Motor Racing（GIANTS Engine 10）车辆模型的完整提取流程与脚本：解包 `.gar` 归档 → 解析 `i3d.shapes` 二进制与 `.i3d` XML → 合并导出**带贴图的单文件 OBJ**（外观 LODA + CPIT 内饰 + SWHEEL 方向盘）。

跑完一轮的实测产出：**123 辆车**（71 台基础车 + 52 台 DLC），4,323 个部件，3,261 处 `map_Kd` 引用零缺失，10,333 张 PNG，合计 11.64 GB。

适用 **Project Motor Racing v2.3.0.3（GIANTS Engine 10）** ｜ 运行环境 Python 3 + numpy + Pillow ｜ 导出物为 OBJ + MTL + PNG

> 本仓库只包含自己写的解析/导出代码与流程文档，不包含任何游戏资源。GIANTS i3d / GAR 格式与游戏资源版权归 GIANTS Software 与 Project Motor Racing 开发方所有，请仅用于个人学习、mod 制作与格式互操作研究。

## 仓库内容

| 路径 | 作用 |
|------|------|
| `src/export_textured.py` | **主入口**：单辆车 / `--all` 全量 / `--dlc` 仅 DLC |
| `src/i3d_shapes_reader.py` | I3DCipher 解密 + `.i3d.shapes` 结构解析（含 numpy 加速） |
| `src/_cipher_keys.py` | 解密用密钥表（被 reader 依赖） |
| `bin/fs-unpack.exe` | GAR 解包工具（**修改版**，见下节） |
| `docs/REPRODUCE.md` | 换台电脑从零复现的操作清单 |
| `docs/PMR-workflow.md` | 完整技术流程、格式逆向要点与踩坑清单 |

## 环境依赖

- **Python 3** + `numpy`、`Pillow`
  ```bash
  pip install -r requirements.txt
  ```
- **Blender 4.2**：仅用于渲染抽查模型，导出流程本身不需要
- **Rust nightly + MinGW**：仅当需要自己重编 `fs-unpack` 时（见下节）

## 快速开始

### 1. 改三处路径

脚本里的路径是硬编码的，换机器前先改：

| 常量 | 位置 | 默认值 |
|------|------|--------|
| `VEHICLES` | `src/export_textured.py:20` | `G:\Games\Project Motor Racing\data\vehicles` |
| `OUT` | `src/export_textured.py:21` | `D:\Games\model output\PMR output` |
| `export_root` | `src/export_textured.py:417`、`:433` | `G:\Games\Project Motor Racing\_export` |

### 2. 解包 DLC 归档（只导基础车可跳过）

```bash
bin/fs-unpack.exe <游戏目录>\dlcS.gar  <解包目录>\dlcS_full
bin/fs-unpack.exe <游戏目录>\dataS.gar <解包目录>\dataS_full
```

### 3. 导出

```bash
python src/export_textured.py Toyota_Supra_GT4   # 单车，参数是车目录名
python src/export_textured.py --all              # 基础车 71 + DLC 52，约 25 分钟
python src/export_textured.py --dlc              # 只导 DLC 车，约 15 分钟
```

输出结构：

```
<OUT>\<车厂>\<车型>\
├── *_merged_textured.obj     # 合并后的单 OBJ
├── *_merged_textured.mtl
├── textures\                 # 车身贴图 PNG
├── liveries\                 # 涂装 PNG
└── _shared\                  # 共享贴图（轮胎/刹车/安全网等）
```

## 关于 `bin/fs-unpack.exe`

这是 [scfmod/fs-utils](https://github.com/scfmod/fs-utils) 的**本地修改版**，不是官方发布产物：

- **修改内容**：原版 gar-lib 会解密文件表里的**所有**条目，但 GIANTS 归档中 `flags=0x0` 的条目（shapes / DDS / anim）本来就是明文存储，解密后反而变成乱码（DDS 头坏成 `40 05 56 34`，shapes 的 version 字段变成 92、76 之类的乱值）。补丁即「`flags==0` 时直接复制原始字节、不解密」。
- **二进制放在 `bin/` 只为省去自己编译**。要自己构建：Rust nightly 工具链（host 设 `x86_64-pc-windows-gnu`）+ w64devkit，把 `libgcc.a` 复制一份为 `libgcc_eh.a`，然后 `cargo build --release -p fs-unpack`。
- 用法：
  ```bash
  fs-unpack.exe <gar> <输出目录>        # 提取全部条目
  fs-unpack.exe --list <gar> NUL        # 只列文件表（name offset size xsize flags）
  ```

## 关键结论（改脚本前必读）

- **`flags=0` 条目是明文**，绝不能 decrypt——这是整套流程最容易踩的坑。
- **v12 `.i3d.shapes`**：`subsets` 之后还有一段**材质名区**（`nsub × u16` + align4），漏了它会导致多 subset 部件的三角形整体错位；子集大小 = `16 + popcount(opts & 0x1E) × 4`，不是固定 32。
- **部件名以 XML 为准**：实体名带 `.001` 后缀时用 XML 名（GIANTS 会把尾翼存成 `BODY_*.001`）；否则用实体名（GIANTS 会把 `WHEEL_LF_*` 错写成 `WHEEL_LR_*`）。
- **Shape 节点自带 rotation 必须应用**（如 M4 的 `-0 -90 0`），否则轮胎装不到轮位。
- 细节见 [`docs/PMR-workflow.md`](docs/PMR-workflow.md)。

## 常见问题

**OBJ 在 Blender 里一片黑 / 没有贴图？** `map_Kd` 是相对路径，`obj` + `mtl` + `textures\` `liveries\` `_shared\` 必须保持相对位置一起拷走。Blender 4.2 导入用 `bpy.ops.wm.obj_import`（老接口 `wavefront.obj.import` 已废弃）。

**为什么有些车看不到轮子或内饰？** 这是过滤规则决定的：外观 LOD 里排除 `INTERIOR` `STEERINGWHEEL` `SWHEEL` `BLUR`，内饰与方向盘来自 CPIT / SWHEEL 文件再并入；个别车把方向盘单独存一份，已单独处理。轮胎是 Shape 自带 transform 挂上去的，若原车 LOD 藏了轮胎就会缺。

**一定要用 `bin/fs-unpack.exe` 吗？** 解包 DLC 时是。原版 gar-lib 会解密 `flags=0` 的明文条目导致乱码，只有补丁版能解对；基础车直接读 `data\vehicles\` 不需要解包。

**能用来导别的 GIANTS 游戏吗？** 只在 `.i3d.shapes` 版本同为 **v12** 且 GAR 布局一致时适用；模拟农场系列的 shapes 版本不同，需要改 `i3d_shapes_reader.py` 的结构解析。

**导出要多久？** 全量 123 辆约 25 分钟（含 DLC 解包后扫描），单车通常十几秒。

## 致谢

- `.i3d.shapes` / GAR 格式研究基于 GIANTS Engine 的公开文件结构，参考了社区已有的 i3d 工具实现
- 解包工具 [scfmod/fs-utils](https://github.com/scfmod/fs-utils)

## 许可

脚本与文档以 [MIT](LICENSE) 发布；`bin/fs-unpack.exe` 来自 scfmod/fs-utils，遵循其原始许可。
