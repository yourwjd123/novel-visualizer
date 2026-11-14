# 第三方代码与素材说明

本应用当前版本作为 GPL-3.0 开源衍生软件分发。许可证见根目录 LICENSE。
新增业务实现由 novel-visualizer 项目维护；下列上游代码保留原作者归属。

## Pagekin

- 上游：https://github.com/EthanYoQ/Pagekin
- 维护者：EthanYoQ / Pagekin contributors。
- 固定参考提交：707d157e1316e2eb363ba522a4eabde65c08ebff。
- 许可证：GPL-3.0，完整文本见 LICENSE。
- 采用并改造：StageTabs.tsx 中标签键盘导航与选中处理；纸墨设计系统中统一表面、文字、强调色和间距的组织方法。
- 对应文件：frontend/src/components/WorkspaceTabs.jsx、frontend/src/style.css。
- 修改：四个横向工作入口、系统侧栏、视觉资产和情节插图页面；不包含其小说创作流程、品牌图标或内置字体。

## Story Asset Studio

- 上游：https://github.com/y083245/ai-story-asset-studio-AIGC
- Copyright (c) 2026 Story Asset Studio contributors。
- 固定参考提交：612f83b1bc8b771fbd52f3408b2cd507960c8e90。
- 许可证：MIT，完整文本见 licenses/story-asset-studio-MIT.txt。
- 采用并改造：AssetImageCard 的缩略图失败状态、可选中卡片和详情操作组织；对应 frontend/src/components/ImageCard.jsx。
- 修改：适配本地 QWebChannel 数据接口、档案/参考图/成果三类卡片、账户和项目范围、无到期删除的回收站。
- 未采用其 Docker/PostgreSQL/Redis 部署、明文模型密钥配置、自动重试和固定图片过期策略。

## 其他依赖

- React / React DOM：MIT，见 licenses/react-MIT.txt、licenses/react-dom-MIT.txt。
- Lucide 图标：ISC（含相关上游声明），见 licenses/lucide-ISC.txt。
- PySide6 / Qt：按其 LGPL/GPL/商业许可条件提供；本项目使用动态链接的开源发行包。上游：https://www.qt.io/licensing/ 与 https://code.qt.io/ 。
- Qt WebEngine 使用 Chromium；相关开源代码与通知由 Qt WebEngine 上游提供：https://doc.qt.io/qt-6/qtwebengine-licensing.html 。
- Python 依赖按 requirements.txt 的各自上游许可使用；构建工具 Vite、PyInstaller 不改变被打包应用的许可。

本应用未绑定上述项目的官方身份，不使用其名称作为本产品品牌。

## 演示素材

novelviz/demo/ 内图片为本项目制作的 AI 演示素材，小说文本为虚构示例。
它们用于明确标记的离线演示项目，不代表用户模型的实际输出、真实原著证据或模型质量承诺。
演示不会调用用户配置的模型服务。
