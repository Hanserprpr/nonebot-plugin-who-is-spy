<div align="center">
  <img src="https://s2.loli.net/2022/06/16/opBDE8Swad5rU3n.png" width="180" height="180" alt="NoneBotPluginLogo">
  <br>
  <p><img src="https://s2.loli.net/2022/06/16/xsVUGRrkbn1ljTD.png" width="240" alt="NoneBotPluginText"></p>
</div>

<div align="center">

# nonebot-plugin-who-is-spy

_✨ 一个谁是卧底小游戏插件 ✨_


<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/Hanserprpr/nonebot-plugin-who-is-spy.svg" alt="license">
</a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-who-is-spy">
    <img src="https://img.shields.io/pypi/v/nonebot-plugin-who-is-spy.svg" alt="pypi">
</a>
<img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">

</div>

一个基于 **[NoneBot2](https://nonebot.dev/)** 的群聊游戏插件 —— **谁是卧底**  
支持 **群聊轮流发言** + **私聊匿名投票**，带有胜场统计、排行榜、胜率榜等功能。

## 📖 介绍

`nonebot-plugin-who-is-spy` 是一个基于 [NoneBot2](https://v2.nonebot.dev/) 开发的多人群聊游戏插件，复刻了经典的 **谁是卧底** 桌游玩法。  
它支持在 QQ 群里发起游戏，玩家轮流发言，通过私聊匿名投票淘汰嫌疑人，直到一方胜利。  

特点：
- **规则完整**：平民、卧底、白板三种身份，还原线下游戏体验  
- **私聊投票**：保护投票隐私，避免被针对  
- **自动化流程**：发言、投票、淘汰、胜负判定全程自动进行  
- **数据统计**：记录胜场、参与次数，支持排行榜与胜率榜  
- **可定制化**：词库、玩家人数、白板开关、身份提示等均可配置

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-who-is-spy

</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details>
<summary>pip</summary>

    pip install nonebot-plugin-who-is-spy
</details>
<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-who-is-spy
</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-who-is-spy
</details>
<details>
<summary>conda</summary>

    conda install nonebot-plugin-who-is-spy
</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_template"]

</details>

## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的必填配置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| MIN_PLAYERS | 否 | 4 | 最少人数 |
| MAX_PLAYERS | 否 | 12 | 最大人数 |
| DEFAULT_UNDERCOVERS | 否 | 1 | 默认卧底人数 |
| ALLOW_BLANK | 否 | True | 是否允许白板 |
| SHOW_ROLE_DEFAULT | 否 | False | 发词时是否显示身份 |
| DATA_DIR | 否 | `"/data/undercover/"` | 数据目录 |
| WORD_FILE | 否 | `"undercover_words.json"` | 词库文件 |
| CONFIG_PATH | 否 | `"config.json"` | 游戏配置项文件 |
| STATS_PATH | 否 | `"stats.json"` | 游戏统计数据 |

## 🎉 使用

### 指令

- 在群内发送 `卧底帮助` 即可获取帮助

```sh
🎮 谁是卧底 - 群聊版玩法说明
——————————
【开局】
卧底开局 [卧底人数] [blank]  → 创建房间（可选参数：卧底人数，blank=有白板）
加入   → 进入房间
发身份 → 房主开始游戏并私聊词语

【发言阶段】
- 系统会在群里公布发言顺序
- 轮到谁，谁直接在群里说一句描述
- 每人一句话，依次发完自动进入投票

【投票阶段（私聊进行）】
- 机器人私聊存活玩家投票序号列表
- 私聊直接回复数字：0=弃权，数字=投票对象

【胜负判定】
- 卧底全出局 → 平民胜利
- 卧底数≥平民数 → 卧底胜利

【常用指令】
状态   → 查看当前局势和投票序号
复盘   → 查看上一局记录
结束卧底 → 强制结束当前局
身份提示 开/关 → 设置私聊是否提示身份
卧底帮助 → 查看本说明
胜率榜 / 我的胜率 → 查看胜率 
```

### 效果图

![alt text](dd293f33ba2a5fab033aa7829a44c20a.jpg)
