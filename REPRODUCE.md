# PMR 车辆导出 — 新电脑复现指南

> 从零复现 Project Motor Racing 车辆模型导出（123 辆，含 DLC）所需的关键文件与步骤。

## 一、关键文件清单（全部拷贝即可）

| 文件/目录 | 作用 | 必需 |
|-----------|------|------|
| `D:\Games\Tools\I3DShapesTool\export_textured.py` | **主入口**：单车 / `--all` 全量 / `--dlc` DLC车 | ✅ |
| `D:\Games\Tools\I3DShapesTool\blender_ref\i3d_shapes_reader.py` | I3DCipher 解密 + shapes 实体读取 | ✅ |
| `D:\Games\Tools\I3DShapesTool\blender_ref\_cipher_keys.py` | 解密密钥表（被 reader 依赖） | ✅ |
| `D:\Games\Tools\fs-utils-src\target\release\fs-unpack.exe` | **GAR 解包**（修复版：flags=0 明文） | ✅ |
| `D:\Games\Tools\I3DShapesTool\gar_cipher.py` | GAR 密码 Python 实现（研究用） | 可选 |
| `D:\Games\Tools\I3DShapesTool\gar_table.py` | GAR 文件表列取（研究用） | 可选 |
| `D:\Games\Tools\I3DShapesTool\render_one.py` | Blender 渲染四视图（验证用） | 可选 |

> 最小集 = `export_textured.py` + `blender_ref\`（2个文件）+ `fs-unpack.exe`。
> 若 fs-unpack.exe 不便拷贝，源码在 `D:\Games\Tools\fs-utils-src\`（Rust nightly + MinGW 编译，见下）。

## 二、环境依赖

1. **Python 3**（需 `numpy` + `Pillow`）
   ```text
   pip install numpy pillow
   ```
2. **Blender 4.2**（可选，仅渲染验证）
   ```text
   C:\Program Files\Blender Foundation\Blender 4.2\blender.exe
   ```
3. **Rust + MinGW**（仅当需重编 fs-unpack 时）
   - rustup（nightly 工具链，host 设为 `x86_64-pc-windows-gnu`）
   - w64devkit（gcc），并把 `libgcc.a` 复制一份为 `libgcc_eh.a`
   - `cargo build --release -p fs-unpack`（在 fs-utils-src 下）

## 三、复现步骤

### 1. 准备游戏数据
- 基础车：`G:\Games\Project Motor Racing\data\vehicles\`（直接可用）
- DLC 车：需先解包归档
  ```text
  fs-unpack.exe dlcS.gar  <out>\dlcS_full
  fs-unpack.exe dataS.gar <out>\dataS_full
  ```
  ⚠️ 必须用**修复版** fs-unpack（flags=0 条目是明文，原版会解出乱码）

### 2. 导出
```text
# 单车测试
python export_textured.py Toyota_Supra_GT4

# 全部（基础车 71 + DLC 52 = 123 辆，约 25 分钟）
python export_textured.py --all

# 仅 DLC 车
python export_textured.py --dlc
```

### 3. 输出
`D:\Games\model output\PMR output\<车厂>\<车型>\`
- `*_merged_textured.obj` + `.mtl`（外观 LODA + CPIT + SWHEEL 合并）
- `textures\` `liveries\` `_shared\`（PNG 贴图）

## 四、核心格式知识（改脚本前必读）

- **v12 .i3d.shapes**：subsets 后有材质名区（nsub×u16+align4）；头部 BV=(cx,cy,cz,r) 可校验
- **GAR**：magic@0x60，文件表@0x200（512B/项，GarCipher 加密）；**flags=0 条目明文**
- **XML 权威名规则**：实体名含 `.001` → 用 XML 名（尾翼）；否则用实体名（GIANTS 会把 WHEEL_LF 错写成 WHEEL_LR）
- **部件过滤**：LOD 排除 INTERIOR/STEERINGWHEEL/SWHEEL/BLUR；CPIT 保留 INTANIM/INTERIOR/STEERINGWHEEL/SWHEEL/MIRROR_C
- 详细流程与已修问题清单：知识库 `RAC\workflow\Project Motor Racing.md`

## 五、输出验收标准

- 每车 1 个 merged OBJ，部件数 30-45
- `map_Kd` 引用 0 缺失
- 前轮毂名为 `*_WHEEL_LF_LODA` / `*_WHEEL_RF_LODA`（不是 LR/RR）
- 轮子/刹车/方向盘位置与场景树节点吻合（可用 render_one.py 渲染抽查）
