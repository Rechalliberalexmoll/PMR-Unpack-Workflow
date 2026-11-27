# PMR 车辆导出 — 新电脑复现指南

> 从零复现 Project Motor Racing 车辆模型导出（123 辆，含 DLC）所需的关键文件与步骤。
> 完整技术流程与踩坑清单见 [`PMR-workflow.md`](PMR-workflow.md)。

## 一、关键文件清单

仓库内已按目录组织好，整包 clone 即可：

| 仓库路径 | 作用 | 必需 |
|-----------|------|------|
| `src/export_textured.py` | **主入口**：单车 / `--all` 全量 / `--dlc` DLC 车 | ✅ |
| `src/i3d_shapes_reader.py` | I3DCipher 解密 + shapes 实体读取 | ✅ |
| `src/_cipher_keys.py` | 解密密钥表（被 reader 依赖） | ✅ |
| `bin/fs-unpack.exe` | **GAR 解包**（补丁版：flags=0 明文） | ✅ |

> 最小集 = `src/` 三个 python 文件 + `bin/fs-unpack.exe`，四个文件必须放在同一目录层级里
> （`export_textured.py` 靠同目录导入 `i3d_shapes_reader`，后者再导入 `_cipher_keys`）。
> 不想用仓库里的 exe，源码在 [scfmod/fs-utils](https://github.com/scfmod/fs-utils)，自己打上面那个补丁后编译（见下）。

## 二、环境依赖

1. **Python 3**（需 `numpy` + `Pillow`）
   ```text
   pip install -r requirements.txt
   ```
2. **Blender 4.2**（可选，仅渲染验证）
   ```text
   C:\Program Files\Blender Foundation\Blender 4.2\blender.exe
   ```
3. **Rust + MinGW**（仅当需重编 fs-unpack 时）
   - rustup（nightly 工具链，host 设为 `x86_64-pc-windows-gnu`）
   - w64devkit（gcc），并把 `libgcc.a` 复制一份为 `libgcc_eh.a`
   - `cargo build --release -p fs-unpack`（在 fs-utils 源码目录下）

## 三、复现步骤

### 1. 改路径

`src/export_textured.py` 顶部和 main 里共三处硬编码路径（`VEHICLES` / `OUT` / `export_root`），按新机器实际情况改掉。

### 2. 准备游戏数据
- 基础车：`<游戏目录>\data\vehicles\`（直接可用）
- DLC 车：需先解包归档
  ```text
  bin\fs-unpack.exe dlcS.gar  <out>\dlcS_full
  bin\fs-unpack.exe dataS.gar <out>\dataS_full
  ```
  ⚠️ 必须用**补丁版** fs-unpack（flags=0 条目是明文，原版会解出乱码：DDS 头坏成 `40 05 56 34`、shapes version 变乱值）

### 3. 导出
```text
# 单车测试
python src/export_textured.py Toyota_Supra_GT4

# 全部（基础车 71 + DLC 52 = 123 辆，约 25 分钟）
python src/export_textured.py --all

# 仅 DLC 车
python src/export_textured.py --dlc
```

### 4. 输出
`<OUT>\<车厂>\<车型>\`
- `*_merged_textured.obj` + `.mtl`（外观 LODA + CPIT + SWHEEL 合并）
- `textures\` `liveries\` `_shared\`（PNG 贴图）

## 四、核心格式知识（改脚本前必读）

- **v12 .i3d.shapes**：subsets 后有材质名区（nsub×u16+align4）；头部 BV=(cx,cy,cz,r) 可校验
- **GAR**：magic@0x60，文件表@0x200（512B/项，GarCipher 加密）；**flags=0 条目明文**
- **XML 权威名规则**：实体名含 `.001` → 用 XML 名（尾翼）；否则用实体名（GIANTS 会把 WHEEL_LF 错写成 WHEEL_LR）
- **部件过滤**：LOD 排除 INTERIOR/STEERINGWHEEL/SWHEEL/BLUR；CPIT 保留 INTANIM/INTERIOR/STEERINGWHEEL/SWHEEL/MIRROR_C
- 详细流程与已修问题清单：[`PMR-workflow.md`](PMR-workflow.md)

## 五、输出验收标准

- 每车 1 个 merged OBJ，部件数 30-45
- `map_Kd` 引用 0 缺失
- 前轮毂名为 `*_WHEEL_LF_LODA` / `*_WHEEL_RF_LODA`（不是 LR/RR）
- 轮子/刹车/方向盘位置与场景树节点吻合（可用 Blender 渲染抽查，见 workflow 文档）
