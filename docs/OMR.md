# 三情形 OMR：实测、原理与代码

这份文档保留了原研究原型（`omr_agent`）的结论和用法，并说明它如何被接进
现在的 Web 服务。产品里的“三情形”指：

1. **清晰印刷谱**（数字渲染/高清截图）——Audiveris 强；
2. **手机照片**（透视、阴影、JPEG）——两者都可用，Audiveris 往往更完整；
3. **真实扫描 / 低分辨率 / 旧刻印**——homr 明显更强。

结论不是“选一个最好的引擎”，而是**同时跑、展示候选、按结构选优**。

---

## 1. 九样本结果（原研究测试）

测试对象：Audiveris 5.11.0 vs homr 0.7.0（CPU）。
指标：note-F1（音高 + onset/时值容差 0.26 四分音符）。
数据：OLiMPiC 1.0 Scanned（CC BY-SA 4.0）；干净样本由 Verovio 从真值渲染，
退化样本由脚本合成。

| 样本 | 类型 | 真值音符 | Audiveris note-F1 | homr note-F1 | 选中 |
|---|---|---:|---:|---:|---|
| 干净整行 | clean | 81 | **100%** | 9.9% | Audiveris |
| 中段缺拍号 | clean | 64 | **100%** | **100%** | 平手 |
| 相邻 system 残片 | clean | 115 | 19.3% | **90.7%** | homr |
| 手机照片 | photo | 81 | **100%** | 82.7% | Audiveris |
| 真实扫描 A | scan | 85 | 35.1% | **100%** | homr |
| 真实扫描 B | scan | 77 | 9.2% | **100%** | homr |
| 真实扫描 C（更难的旧谱） | scan | 75 | 0% | **15.9%** | homr（都不够） |
| 真实低清扫描 593×146 | scan | 81 | 0% | **61.7%** | homr |
| 强退化 620px | stress | 81 | 失败 | **100%** | homr |

- 9 个样本中 6 个达到 **100%** note-F1。
- 没有单一引擎通吃：Audiveris 在干净谱/照片上更稳，homr 在真实扫描/低清/退化上更强。
- “相邻 system 残片”是选型分水岭：Audiveris 19.3%，homr 90.7%。只看一个
  引擎会误判“引擎不行”，其实是引擎选错。
- 真实低清扫描上，homr 61.7% 仍意味着约 38% 音符不对，必须人工/VLM 复核。
- 干净 Verovio 渲染上 homr 只有 9.9%，不能因为它在扫描上强就默认全用它。

> N=9，来自一首曲子的若干 system + 3 个真实扫描 + 退化版本，不能外推为
> 产品准确率。note-F1 只检查音高/起始/时值，不检查声部、连音线、歌词、力度。
> 完整图表和讨论在原调研报告中；本仓库保留结论与可复现 CLI。

---

## 2. 指标与选优

### note-F1

- 遍历 `Score` 下所有 `Note` / `Chord`，和弦拆成多个 notehead；
- 事件包含 `part, measure, onset, duration, midi`；
- 预测与真值按 onset/duration 容差 0.26 四分音符、MIDI 音高相同做贪心一对一匹配；
- `precision = TP / pred`，`recall = TP / gt`，`F1 = 2PR/(P+R)`。

真值 F1 在 Web 产品里**只用于展示评测**，不参与生产选优（避免“用答案选答案”）。
自动化测试/研究 CLI 仍可用 `--oracle` 按 F1 选。

### 结构启发式

每个候选先解析 MusicXML，计算：

- `measures`：带拍号的小节数；
- `valid_ratio`：小节内容是否填满名义长度（容差 0.26 四分音符）；
- `notes`：notehead 数；
- `coverage = min(1, notes / (measures × 2))`，无小节时按 20 个音符归一；
- `quality = 0.55 × valid_ratio + 0.25 × coverage + 0.20 × engine_prior`。

`engine_prior`：

- 扫描/照片风格且引擎是 homr：+0.18；
- 干净数字图且引擎是 Audiveris：+0.18；
- 其余 0。

这个分数偏爱“结构完整、内容充实”的候选，不等同于音乐学正确率；所以 UI 同时
展示两个候选、音符数、合法率、质量分和可选 note-F1，并标记低置信结果。

---

## 3. 处理流水线

```text
输入图片
  └─ content_bbox 裁掉空白边
     └─ estimate_skew：旋转让谱线最水平（投影方差最大）
        └─ upscale：短边不足 1800px 时放大（最多 3200px）
           ├─ upright：去倾斜 + 放大
           ├─ clahe：局部对比度增强
           └─ binary：自适应二值化
                └─ 引擎
                   ├─ Audiveris：batch/transcribe/export -> .mxl -> music21 -> MusicXML
                   └─ homr：原图 -> local ONNX -> .musicxml
                      └─ 候选解析/结构校验/选优
                         ├─ best.musicxml
                         ├─ best.mid / best.wav
                         ├─ notes.csv
                         ├─ piano_roll.png
                         └─ report.json
```

- Web 产品的 `compare` 模式固定跑 Audiveris + homr；单引擎模式只跑指定引擎。
- 可以在 `.env` 里用 `OMR_ENGINES` 改 `compare` 的默认引擎集合。
- worker 在成功生成音频后会删除 `preprocessed/` 与 `engines/`，只保留交付物，
  节省轻量服务器磁盘。
- 单个引擎失败/超时不会杀掉整个任务；另一个候选仍可被选中。
- 两个都失败 -> 任务 `error`，退还免费额度，前端显示可读错误。

---

## 4. 引擎适配

### Audiveris

- 通过 `AUDIVERIS_BIN` 指定二进制；worker 镜像中是
  `/opt/audiveris/bin/Audiveris`。
- 命令：`-batch -transcribe -export -output <dir> <input>`。
- 运行环境：`_JAVA_OPTIONS` 设置 headless、临时目录和 `user.home`；
  `AUDIVERIS_HEAP`（构建期）写入 jpackage 配置，默认 1536m。
- 输出 `.mxl` 再用 music21 转成未压缩 MusicXML，便于前端/其他软件直接打开。
- macOS 本地开发默认探测
  `/Applications/Audiveris.app/Contents/MacOS/Audiveris`；Linux 用
  `/opt/audiveris/bin/Audiveris`。

### homr

- 优先用 `HOMR_BIN`/`PATH` 中的 `homr`；本地没装时回退到
  `uvx --from homr==0.7.0 homr`（首次会下载环境与模型）。
- worker 镜像在构建期 `homr --init` 预下载 ONNX + OCR 权重，运行时不需要联网。
- homr 把 `.musicxml` 写在输入图旁边；适配器会把输入复制到独立目录，再收集结果。

### oemer（可选，仅 CLI）

原研究里的 oemer 适配器保留在 `engines.py`，但不进入 Web 的三种模式。它的结构
bug 和 276 秒耗时不适合在线服务；保留是为了复现旧实验。

---

## 5. CLI 复现

```bash
cd services/backend
# 需要真实引擎；本地 mock 时输出是固定示例

# 单图 + 真值
.venv/bin/python -m omr_agent.compare 图片.png --out /tmp/omr --gt 真值.musicxml

# 指定引擎/视图
.venv/bin/python -m omr_agent.pipeline 图片.png --out /tmp/omr \
  --engines audiveris --variants upright,clahe,binary

# 质量路由（低分辨率走 homr，高清走 Audiveris）
.venv/bin/python -m omr_agent.route 图片.png --out /tmp/omr

# 只做评测
.venv/bin/python -m omr_agent.metrics 真值.musicxml 预测.musicxml

# 把 MusicXML 变成可听文件
.venv/bin/python -m omr_agent.play /tmp/omr/best.musicxml \
  --wav /tmp/omr/play.wav --midi /tmp/omr/play.mid --png /tmp/omr/roll.png
```

`compare` 的报告不包含服务器绝对路径；音频/结果文件在输出目录中。

---

## 6. 本地安装真实引擎

### Audiveris

- macOS：下载 `.dmg`，安装后设置：
  ```bash
  export AUDIVERIS_BIN=/Applications/Audiveris.app/Contents/MacOS/Audiveris
  ```
- Ubuntu 24.04：下载官方 `.deb`，`sudo apt install ./Audiveris-5.11.0-ubuntu24.04-x86_64.deb`，
  默认 `/opt/audiveris/bin/Audiveris`。
- 需要 Java 运行时；官方安装包自带。旧版/自行构建时请确保 Java 21+。

### homr

```bash
cd services/backend
WITH_HOMR=1 ../../scripts/setup.sh   # 推荐；或
.venv/bin/pip install 'homr==0.7.0'
# 首次真实运行会下载模型；也可手动：
.venv/bin/homr --init
```

然后：

```bash
OMR_MOCK=false pnpm dev
```

如果本机没有任何引擎，`pnpm dev` 的 mock 模式可以完整走通产品流程（但结果不是
真实识别）。

---

## 7. 已知限制（与产品路线）

- 不训练模型；完全依赖 Audiveris/homr + 预处理 + 选优。
- 只做 measure validity 级别的校验；没有完整的乐理约束修复、渲染回比对、VLM
  裁决。
- 低分辨率/复杂钢琴谱仍可能错；结果页明确提示人工复核。
- 一次一页；PDF 只第一页。
- N=9 的测试不足以估计线上准确率；上线后建议按输入类型采样人工评估。
- Audiveris/homr 是 AGPL-3.0；网络服务/生产使用前请阅读 [NOTICE](../NOTICE)。

后续值得做的方向：

1. 按输入质量做**路由**（低清直接 homr，高清直接 Audiveris，边界才双跑）以省 CPU；
2. 渲染回比对：把 MusicXML 重新排版成图，和输入做结构相似度；
3. 置信度校准：用线上人工复核结果训练一个轻量选优器；
4. 多页 PDF / 多 system 拼接；
5. 管理后台与多用户额度。
