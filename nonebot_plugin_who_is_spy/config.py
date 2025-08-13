from pydantic import BaseModel, Extra
import os

class Config(BaseModel, extra=Extra.ignore):
    """插件配置"""
    MIN_PLAYERS: int = 4                # 最少玩家数
    MAX_PLAYERS: int = 12               # 最多玩家数
    DEFAULT_UNDERCOVERS: int = 1        # 默认卧底人数
    ALLOW_BLANK: bool = True            # 是否允许白板
    SHOW_ROLE_DEFAULT: bool = False     # 私聊发词时是否显示身份（默认关闭）
    DATA_DIR: str = os.path.join("data", "undercover") # 数据目录
    WORD_FILE: str = ""                 #游戏词库
    CONFIG_PATH: str = ""
    STATS_PATH: str = ""
