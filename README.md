# BlendPlay

在 Blender 中编写 Python 游戏脚本、编辑场景并运行整个游戏的轻量插件。

这是独立的通用引擎项目。**DOORS 游戏不包含在此仓库，也未通过本仓库授权发布。**

## 能做什么

- 中文游戏 IDE、场景选择跟随代码、模型组件及独立脚本文件。
- 运行整个游戏，支持全屏、退出后恢复编辑状态。
- 第一人称、第三人称和斜角俯视；鼠标视角、第一人称步伐晃动。
- 玩家控制器、人形骨骼与基础动画、移动、冲刺、跳跃及台阶。
- 平台碰撞、空气墙、金币、触发区域、NPC、灯光和镜头脚本。
- 按名称查找模型、生成及销毁运行时对象。
- 不需额外运行时 Python 库。

## 安装

当前验证版本：Blender 5.1.2；最低声明版本为5.1。其他版本尚未验证。

1. 下载本项目，运行 `python3 scripts/build_release.py`（Windows：`py -3 scripts/build_release.py`）。
2. Blender → 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择 `dist/BlendPlay_Addon.zip`，启用 BlendPlay。
3. 在3D视图的 **BlendPlay** 面板中创建游戏项目，选择视角，再进入游戏 IDE。
4. 点击“运行整个游戏”，而不是 Blender 原生的“运行当前文本”。

可选：运行 `zsh 安装.command`（macOS终端）或 `安装.cmd`（Windows），安装插件及“Game 游戏”启动模板。脚本只安装本项目和启动模板，不改写个人偏好；在普通工程中首次使用时，请手动启用插件。找不到 Blender 时设置 `BLENDER_BIN` 指向其可执行文件。

源码开发无需安装到个人配置：`blender --background --factory-startup --python tests/blender_smoke.py`。

## 控制

WASD 移动，Shift 冲刺，空格跳跃，鼠标转向，Esc 退出运行。1/2/3 切换视角。脚本可以自行更改这些行为。

详见 [快速开始](docs/QUICKSTART.md)、[脚本 API](docs/API.md)、[开源范围](docs/SCOPE.md)。

## 开发与验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/build_release.py
blender --background --factory-startup --python tests/blender_smoke.py
```

`blender` 不在PATH时，请用 Blender 可执行文件完整路径代替。CI检查源码与分发边界；Blender运行测试需本地执行上面的命令。

## 当前限制

这是 Blender 内的游戏运行器，并非独立可执行游戏导出器，也不承诺达到 Unity／UE 的完整功能。碰撞采用包围盒，不是通用的网格物理引擎；大型场景仍需自行优化。自动化测试不能替代不同平台上的交互和性能测试。

游戏脚本通过 Python 执行，具备当前 Blender 进程的权限。只运行可信脚本和工程；不要把它当作安全沙箱。

## 许可

本仓库源码使用 **GPL-3.0-or-later**，完整条款见 [LICENSE](LICENSE)。请只对本仓库实际包含的文件使用该许可；不要据此推断任何外部游戏、模型、贴图、音乐或其他作品已获授权。
