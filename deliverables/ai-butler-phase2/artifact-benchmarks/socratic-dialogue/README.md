# 引导式解题/分步讲解 基准库（socratic-dialogue）

> 用途：S-B4「后台引导式解题」产出的验收基准。验收方式 = 我方 AI 引导会话与下列真实样本并排对比。下载日期：2026-09-02。

## 样本清单（5 份）

| 文件 | 来源 | 优秀在哪 |
|---|---|---|
| `tora-corpus-math_分步CoT推理样例.jsonl` | 本地既有基准资产 `D:\AI对话\ToRA\data\tora\examples.jsonl`（清华 THUNLP ToRA 语料，原始仓库 https://github.com/microsoft/ToRA ） | 真实数学题的完整分步推理链：每步一个推导动作、自然语言+公式交替、末尾收束到 `gt` 答案——分步粒度的金标准 |
| `prm800k_过程评分标注界面_官方样例.png` | 本地既有基准资产 `D:\AI对话\prm800k\prm800k\img\interface.png`（OpenAI PRM800K 官方界面图） | 步骤级评分形态：每一步推理被独立标注正/负——启发我们「引导步骤」应可独立判对错，为断点续引与纠错提供粒度 |
| `xiaoyuan-ai_appstore_拍照搜题分步解析界面.png` | App Store 中国区小猿AI 页 https://apps.apple.com/cn/app/id1325419855 （浏览器实拍） | 竞品解题入口形态：拍照→题面识别→分步解析的入口编排 |
| `xiaoyuan-ai_appstore_解题讲解截图轮播.png` | 同上（下滚实拍） | 轮播内含真实解题页：一题多解（「方法二：辅助确定直角三角形面积」）、步骤编号、图形+公式混排——「一题多解+步骤编号+图文混排」是讲解页排版基准 |
| `khanmigo-ai_官网_引导式AI导师界面.png` | Khanmigo 官网 https://www.khanmigo.ai/ （浏览器实拍） | 引导式对话的产品叙事：学生气泡「Can you help me solve this?」+ AI 反问引导而非直给答案——苏格拉底式定位的表达基准 |

## 对 AI 生成物的验收标准（S-B4 产出 vs 本基准并排对比）

1. **不泄题**：引导链中途不得直接出现最终答案；答案只出现在末段且默认折叠（对照 Khanmigo「反问引导」形态）。
2. **步骤粒度**：每步只做一个动作（识别条件→选方法→推一步→检验），对照 ToRA 步骤链，禁止一步跳到结论。
3. **一题多解**：≥1 种解法路径，方法间有「方法一/方法二」标注（对照小猿AI 讲解页）。
4. **图文混排**：涉及几何/函数的步骤必须配图（我方 MathFigure/MathFigure3D），公式用 LaTeX 渲染不出现裸代码。
5. **错误可回退**：学生答错某步时，从该步重新引导而非整题重来（对照 PRM800K 步骤级评分粒度）。
6. **中文表达**：步骤文案是「人话」引导（提问式），禁止「首先让我们分析一下…」式 AI 腔。

## 搜集失败记录（如实）

- Photomath / Microsoft Math Solver / Gauth 均已从中国区 App Store 下架，商店页 404 或跳「发生错误」，未能取得其官方截图（Photomath 页跳转 App Store Today 页已弃用）。
- Khanmigo 应用内界面需登录 khanmigo.khanacademy.org，以官网页替代。
