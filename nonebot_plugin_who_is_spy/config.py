from pydantic import BaseModel, Extra
import os

class Config(BaseModel):
    """插件配置"""
    spy_min_players: int = 4                # 最少玩家数
    spy_max_players: int = 12               # 最多玩家数
    spy_default_undercovers: int = 1        # 默认卧底人数
    spy_allow_blank: bool = True            # 是否允许白板
    spy_show_role_default: bool = False     # 私聊发词时是否显示身份（默认关闭）
    spy_word_file: str = ""                 # 游戏词库
    spy_config_path: str = ""
    spy_stats_path: str = ""
