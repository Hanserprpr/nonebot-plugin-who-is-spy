from __future__ import annotations

import asyncio
import json
import os
import re
import random
from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional, Tuple

from nonebot import on_command, on_message, get_bot, get_plugin_config
from nonebot.params import CommandArg
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageSegment,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11.permission import PRIVATE
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="谁是卧底小游戏",
    description="这是一个用于QQ群的谁是卧底小游戏插件",
    usage="发送 卧底帮助 获取帮助",

    type="application",
    
    homepage="https://github.com/Hanserprpr/nonebot-plugin-who-is-spy",

    config=Config,

    supported_adapters={"~onebot.v11"},
)

plugin_config = get_plugin_config(Config)

# ===================== 常量 & 路径 =====================
MIN_PLAYERS = plugin_config.MIN_PLAYERS
MAX_PLAYERS = plugin_config.MAX_PLAYERS
DEFAULT_UNDERCOVERS = plugin_config.DEFAULT_UNDERCOVERS
ALLOW_BLANK = plugin_config.ALLOW_BLANK
SHOW_ROLE_DEFAULT = plugin_config.SHOW_ROLE_DEFAULT

DATA_DIR = plugin_config.DATA_DIR
WORD_FILE = plugin_config.WORD_FILE or os.path.join(DATA_DIR, "undercover_words.json")
CONFIG_PATH = plugin_config.CONFIG_PATH or os.path.join(DATA_DIR, "config.json")
STATS_PATH = plugin_config.STATS_PATH or os.path.join(DATA_DIR, "stats.json")

# ===================== 保证数据目录 =====================
os.makedirs(DATA_DIR, exist_ok=True)

# ===================== 词库（JSON） =====================
WORD_BANK: List[Tuple[str, str]] = []

def load_words_from_json(path: str = WORD_FILE) -> int:
    """从 JSON 文件加载词对，全量覆盖到 WORD_BANK，返回覆盖后的数量。"""
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        new_pairs: List[Tuple[str, str]] = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                civ, uc = str(item[0]).strip(), str(item[1]).strip()
                if civ and uc:
                    new_pairs.append((civ, uc))

        # ⭐ 关键：用“覆盖”替换原来的 insert 逻辑
        WORD_BANK[:] = new_pairs
        return len(new_pairs)
    except Exception as e:
        print(f"[undercover] 载入词库失败: {e}")
        return 0

# 模块载入时自动加载一次
try:
    _loaded = load_words_from_json(WORD_FILE)
    if _loaded:
        print(f"[undercover] 已从 {WORD_FILE} 加载 {_loaded} 对词")
except Exception:
    pass

# ===================== 简易持久化（群配置 & 胜场） =====================
_store_lock = asyncio.Lock()

def _load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _atomic_write_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# 结构：
# config_store = {"groups": { "<gid>": {"show_role": bool}, ...}}
# stats_store  = {"groups": { "<gid>": { "<uid>": int_wins, ...}}}
config_store: Dict = _load_json_file(CONFIG_PATH, {"groups": {}})
stats_store: Dict = _load_json_file(STATS_PATH, {"groups": {}})

async def get_group_show_role(gid: int) -> bool:
    async with _store_lock:
        g = config_store.setdefault("groups", {}).get(str(gid), {})
        if "show_role" not in g:
            return SHOW_ROLE_DEFAULT
        return bool(g["show_role"])

async def set_group_show_role(gid: int, value: bool):
    async with _store_lock:
        groups = config_store.setdefault("groups", {})
        g = groups.setdefault(str(gid), {})
        g["show_role"] = bool(value)
        _atomic_write_json(CONFIG_PATH, config_store)

async def add_wins(gid: int, uids: List[int], count: int = 1):
    """给本群的一批用户+count胜场"""
    async with _store_lock:
        groups = stats_store.setdefault("groups", {})
        gstats = groups.setdefault(str(gid), {})
        for uid in uids:
            key = str(uid)
            gstats[key] = int(gstats.get(key, 0)) + count
        _atomic_write_json(STATS_PATH, stats_store)

async def get_wins(gid: int, uid: int) -> int:
    async with _store_lock:
        return int(stats_store.get("groups", {}).get(str(gid), {}).get(str(uid), 0))

async def get_top_wins(gid: int, topn: int = 10) -> List[Tuple[int, int]]:
    async with _store_lock:
        g = stats_store.get("groups", {}).get(str(gid), {})
        wins_map = g.get("wins", g)  # 兼容旧结构
        items = [(int(uid), int(w)) for uid, w in wins_map.items() if uid.isdigit()]
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:topn]

async def reset_group_wins(gid: int):
    async with _store_lock:
        groups = stats_store.setdefault("groups", {})
        groups[str(gid)] = {}
        _atomic_write_json(STATS_PATH, stats_store)
        
async def _ensure_group_stats(gid: int) -> Dict:
    """确保本群统计为新结构；如是旧结构则迁移为 {'wins': old_map, 'plays': {}} 并落盘。"""
    groups = stats_store.setdefault("groups", {})
    g = groups.setdefault(str(gid), {})
    if "wins" not in g and "plays" not in g:
        # 旧格式：直接把原映射视为 wins，创建空 plays
        old = dict(g)
        groups[str(gid)] = {"wins": old, "plays": {}}
        _atomic_write_json(STATS_PATH, stats_store)
        return groups[str(gid)]
    # 新格式：补齐缺项
    g.setdefault("wins", {})
    g.setdefault("plays", {})
    return g

async def add_wins(gid: int, uids: List[int], count: int = 1):
    async with _store_lock:
        g = await _ensure_group_stats(gid)
        wins = g["wins"]
        for uid in uids:
            key = str(uid)
            wins[key] = int(wins.get(key, 0)) + count
        _atomic_write_json(STATS_PATH, stats_store)

async def add_plays(gid: int, uids: List[int], count: int = 1):
    """给本群的一批用户 +count 参与局数"""
    async with _store_lock:
        g = await _ensure_group_stats(gid)
        plays = g["plays"]
        for uid in uids:
            key = str(uid)
            plays[key] = int(plays.get(key, 0)) + count
        _atomic_write_json(STATS_PATH, stats_store)

async def get_wins(gid: int, uid: int) -> int:
    async with _store_lock:
        g = stats_store.get("groups", {}).get(str(gid), {})
        # 兼容旧结构
        if "wins" in g:
            return int(g["wins"].get(str(uid), 0))
        return int(g.get(str(uid), 0))

async def get_plays(gid: int, uid: int) -> int:
    async with _store_lock:
        g = stats_store.get("groups", {}).get(str(gid), {})
        if "plays" in g:
            return int(g["plays"].get(str(uid), 0))
        return 0


# ===================== 数据结构（游戏状态） =====================
@dataclass
class Player:
    uid: int
    nickname: str
    is_alive: bool = True
    is_undercover: bool = False
    is_blank: bool = False
    has_spoken_this_round: bool = False
    last_hint: str = ""

@dataclass
class Game:
    group_id: int
    owner_id: int
    ready: bool = False
    allow_blank: bool = ALLOW_BLANK
    word_civilian: str = ""
    word_undercover: str = ""
    players: Dict[int, Player] = field(default_factory=dict)  # uid -> Player
    alive_order: List[int] = field(default_factory=list)      # 发言顺序（uid）
    round_no: int = 0
    votes: Dict[int, Optional[int]] = field(default_factory=dict)    # voter_uid -> target_uid(None=弃权)
    vote_box: Dict[int, int] = field(default_factory=dict)           # target_uid -> count
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    history: List[str] = field(default_factory=list)

    # 私聊数字投票控制
    expecting_pm_vote: Set[int] = field(default_factory=set)  # 本轮等待私聊投票的 uid
    vote_round_tag: int = 0  # 本轮编号（防跨轮误投）

    # 统计标记，防止重复结算胜场
    stats_awarded: bool = False

    def reset_round_flags(self):
        for p in self.players.values():
            p.has_spoken_this_round = False
            p.last_hint = ""
        self.votes.clear()
        self.vote_box.clear()
        self.expecting_pm_vote.clear()
        self.round_no += 1

    def alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.is_alive]

    def alive_ids(self) -> List[int]:
        return [p.uid for p in self.alive_players()]

    def undercovers_alive(self) -> int:
        return sum(p.is_alive and p.is_undercover for p in self.players.values())

    def civilians_alive(self) -> int:
        return sum(p.is_alive and (not p.is_undercover) for p in self.players.values())

    def is_game_over(self) -> Optional[str]:
        u = self.undercovers_alive()
        c = self.civilians_alive()
        if u == 0:
            return "平民阵营胜利！卧底已全部出局。"
        if u >= c:
            return "卧底阵营胜利！卧底人数已不小于平民。"
        return None

# group_id -> Game
games: Dict[int, Game] = {}

# ===================== 工具函数 =====================
async def get_nickname(bot: Bot, gid: int, uid: int) -> str:
    try:
        info = await bot.get_group_member_info(group_id=gid, user_id=uid, no_cache=True)
        return info.get("card") or info.get("nickname") or str(uid)
    except Exception:
        return str(uid)

def ms_at(uid: int) -> MessageSegment:
    return MessageSegment.at(uid)

def current_alive_order(game: Game) -> List[int]:
    return [uid for uid in game.alive_order if game.players[uid].is_alive]

def build_index_map(game: Game) -> Dict[int, int]:
    order = current_alive_order(game)
    return {i: uid for i, uid in enumerate(order, start=1)}

def render_alive_numbered(game: Game) -> str:
    idx_map = build_index_map(game)
    lines = []
    for idx in sorted(idx_map.keys()):
        uid = idx_map[idx]
        p = game.players[uid]
        lines.append(f"{idx}. {p.nickname}")
    return "\n".join(lines)

def is_voting_phase(game: Game) -> bool:
    return bool(game.expecting_pm_vote) and game.vote_round_tag == game.round_no

def pick_words() -> Tuple[str, str]:
    if not WORD_BANK:
        raise RuntimeError("词库为空：请先准备 JSON 并使用「重载词库」加载。")
    return random.choice(WORD_BANK)

def assign_roles(game: Game, undercover_count: int, use_blank: bool):
    ids = list(game.players.keys())
    random.shuffle(ids)

    w_civ, w_uc = pick_words()

    # 50% 概率交换，让“平民/卧底”随机对应两边的词
    if random.random() < 0.5:
        w_civ, w_uc = w_uc, w_civ

    game.word_civilian = w_civ
    game.word_undercover = w_uc


    for uid in ids[:undercover_count]:
        game.players[uid].is_undercover = True

    if use_blank and len(ids) >= 6:
        blank_uid = ids[-1]
        if not game.players[blank_uid].is_undercover:
            game.players[blank_uid].is_blank = True

    game.alive_order = ids[:]
    random.shuffle(game.alive_order)

async def pm_invite_for_voting(bot: Bot, game: Game):
    lines = [
        "【谁是卧底｜投票】",
        f"群：{game.group_id}",
        "",
        "请直接【回复一个数字】完成投票：",
        "  - 回复 0 = 弃权",
        "  - 回复 对方序号 = 投给该玩家",
        "",
        "当前存活（投票序号）：",
        render_alive_numbered(game),
    ]
    msg = "\n".join(lines)

    game.expecting_pm_vote = set(game.alive_ids())
    game.vote_round_tag = game.round_no

    for uid in game.expecting_pm_vote:
        try:
            await bot.send_private_msg(user_id=uid, message=msg)
        except Exception:
            pass

async def _award_wins_if_needed(game: Game):
    """根据当前局势给对应阵营的存活玩家 +1 胜场（只结算一次）"""
    if game.stats_awarded:
        return

    u = game.undercovers_alive()
    c = game.civilians_alive()

    if u == 0:
        # 平民阵营胜利：存活且非卧底玩家（含白板）
        winners = [uid for uid, p in game.players.items()
                   if p.is_alive and not p.is_undercover]
    elif u >= c:
        # 卧底阵营胜利：存活且是卧底的玩家
        winners = [uid for uid, p in game.players.items()
                   if p.is_alive and p.is_undercover]
    else:
        return  # 未结束

    await add_wins(game.group_id, winners, 1)
    game.stats_awarded = True

async def _schedule_cleanup(gid: int, delay: int = 600):
    """在 delay 秒后，若该群没有进行中的局（ready=False），自动清理房间"""
    try:
        await asyncio.sleep(delay)
        game = games.get(gid)
        if game and not game.ready:
            del games[gid]
    except Exception:
        pass

async def settle_and_announce(bot: Bot, game: Game) -> None:
    gid = game.group_id

    # 计票
    game.vote_box.clear()
    for t in game.votes.values():
        if t is None:
            continue
        game.vote_box[t] = game.vote_box.get(t, 0) + 1

    # 全部弃权
    if not game.vote_box:
        game.history.append(f"R{game.round_no} 投票：全部弃权")
        await bot.send_group_msg(group_id=gid, message="🗳 本轮全部弃权。本轮作废，重新发言！")
        game.reset_round_flags()
        return

    # 匿名统计（带序号）
    idx_map = build_index_map(game)
    inv_index = {uid: idx for idx, uid in idx_map.items()}

    lines = ["🗳 本轮投票统计（匿名）：" ]
    for uid, cnt in sorted(game.vote_box.items(), key=lambda x: (-x[1], game.players[x[0]].nickname)):
        idx = inv_index.get(uid, "?")
        lines.append(f"- [{idx}] {game.players[uid].nickname}：{cnt} 票")
    await bot.send_group_msg(group_id=gid, message="\n".join(lines))

    # 找最高票
    max_cnt = max(game.vote_box.values())
    top = [uid for uid, cnt in game.vote_box.items() if cnt == max_cnt]

    if len(top) >= 2:
        game.history.append(f"R{game.round_no} 投票：并列最高票，无人出局")
        await bot.send_group_msg(group_id=gid, message="⚖️ 最高票并列，无人出局！重新发言～")
        game.reset_round_flags()
        return

    # 淘汰
    eliminated = top[0]
    game.players[eliminated].is_alive = False
    role = "卧底" if game.players[eliminated].is_undercover else ("白板" if game.players[eliminated].is_blank else "平民")
    game.history.append(f"R{game.round_no} 出局：{game.players[eliminated].nickname}（{role}）")

    over = game.is_game_over()
    if over:
        # 结算胜场（你之前已经按“仅存活者+1”改过 _award_wins_if_needed）
        await _award_wins_if_needed(game)

        uc = [p.nickname for p in game.players.values() if p.is_undercover]
        blank = [p.nickname for p in game.players.values() if p.is_blank]
        summary = (
            f"🎊 {over}\n"
            f"平民词：{game.word_civilian}\n"
            f"卧底词：{game.word_undercover}\n"
            f"卧底：{', '.join(uc) if uc else '无'}；白板：{', '.join(blank) if blank else '无'}"
        )
        await bot.send_group_msg(
            group_id=gid,
            message=f"🪦 {game.players[eliminated].nickname} 出局！身份：{role}\n" + summary
        )

        # 🆕 标记“已结束”，允许立即开新局；同时保留复盘
        game.ready = False
        game.expecting_pm_vote.clear()
        game.votes.clear()
        game.vote_box.clear()

        await bot.send_group_msg(
            group_id=gid,
            message="本局已结束。现在可以直接发送「卧底开局」开始新的一局；需要查看记录请用「复盘」。\n"
                    "（若不操作，房间会在一段时间后自动清理）"
        )

        # 🆕 安排自动清理（例如 10 分钟后）
        asyncio.create_task(_schedule_cleanup(gid, delay=600))
        return
    else:
        # ✅ 新增：未结束也要公示被票出者（不公开身份）
        await bot.send_group_msg(
            group_id=gid,
            message=f"🪦 {game.players[eliminated].nickname} 被票出！身份将在本局结束后揭晓。"
        )

        # ✅ 新增：准备下一轮（清空发言/票箱，回合数 +1）
        game.reset_round_flags()

        # 提示下一轮发言第一位
        first_uid = current_alive_order(game)[0]
        first_name = game.players[first_uid].nickname
        await bot.send_group_msg(
            group_id=gid,
            message=f"🔔 第 {game.round_no} 轮开始。现在请 {first_name} 发言。"
        )
        return


# ===================== 指令 =====================
cmd_open = on_command("卧底开局", aliases={"开始卧底", "谁是卧底"}, block=True, priority=10)
cmd_join = on_command("加入", block=True, priority=10)
cmd_quit = on_command("退出", block=True, priority=10)
cmd_start = on_command("发身份", aliases={"开始游戏"}, block=True, priority=10)
cmd_status = on_command("状态", aliases={"存活", "存活名单"}, block=True, priority=10)
cmd_vote = on_command("投票", block=True, priority=10)  # 群里仅提示去私聊数字投票
cmd_end = on_command("结束卧底", aliases={"强制结束"}, block=True, priority=10)
cmd_review = on_command("复盘", block=True, priority=10)
cmd_words = on_command("自定义词", block=True, priority=10)
cmd_reload_words = on_command("重载词库", aliases={"加载词库", "载入词库"}, block=True, priority=10)
cmd_help = on_command("卧底帮助", aliases={"谁是卧底帮助", "卧底规则", "卧底玩法"}, block=True, priority=10)
cmd_role_hint = on_command("身份提示", aliases={"显示身份", "showrole"}, block=True, priority=10)
cmd_rank = on_command("卧底排行", aliases={"胜场榜", "卧底榜"}, block=True, priority=10)
cmd_mywins = on_command("我的胜场", block=True, priority=10)
cmd_reset_rank = on_command("重置排行", block=True, priority=10)
cmd_winrate = on_command("胜率榜", aliases={"卧底胜率", "胜率排行"}, block=True, priority=10)
cmd_mywinrate = on_command("我的胜率", block=True, priority=10)

# ========== 群内自由发言（每人一句，自动切换，进入投票） ==========
def _is_group_speaking(event) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    gid = event.group_id
    if gid not in games:
        return False
    game = games[gid]
    if not game.ready or is_voting_phase(game):
        return False
    text = str(event.get_plaintext() or "").strip()
    return bool(text)

group_speak = on_message(rule=Rule(_is_group_speaking), priority=11, block=True)

@group_speak.handle()
async def _(event: GroupMessageEvent, matcher: Matcher):
    gid = event.group_id
    uid = event.user_id
    text = event.get_plaintext().strip()

    game = games[gid]
    if uid not in game.players or not game.players[uid].is_alive:
        return

    async with game.lock:
        order_alive = [pid for pid in game.alive_order if game.players[pid].is_alive]
        next_to_speak = None
        for pid in order_alive:
            if not game.players[pid].has_spoken_this_round:
                next_to_speak = pid
                break

        if next_to_speak is None:
            await pm_invite_for_voting(get_bot(), game)
            await matcher.finish("✅ 本轮发言完毕，进入投票阶段！已私聊你投票说明与序号列表。")
            return

        if uid != next_to_speak:
            want = game.players[next_to_speak].nickname
            await matcher.finish(f"现在轮到【{want}】发言，请稍等～")
            return

        if game.players[uid].has_spoken_this_round:
            await matcher.finish("你本轮已经发过言了，等待下一位～")
            return

        p = game.players[uid]
        p.has_spoken_this_round = True
        p.last_hint = text
        game.history.append(f"R{game.round_no} 发言 —— {p.nickname}：{text}")

        if all(game.players[pid].has_spoken_this_round for pid in order_alive):
            await pm_invite_for_voting(get_bot(), game)
            await matcher.finish(
                "✅ 本轮所有人已发言完毕，进入投票阶段！\n"
                "我已私聊在场玩家投票说明与序号列表，请在私聊里【直接回复数字】完成投票（0=弃权）。"
            )
        else:
            idx = order_alive.index(uid)
            nxt = game.players[order_alive[idx + 1]].nickname
            await matcher.finish(f"✅ 已记录你的发言。\n下一个是：{nxt}")

# ===================== 其余群指令 =====================
@cmd_open.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    gid = event.group_id
    uid = event.user_id
    if gid in games and games[gid].ready:
        await cmd_open.finish("⚠️ 本群已有一局正在进行。可用「结束卧底」强制结束。")

    text = arg.extract_plain_text().strip()
    undercovers = DEFAULT_UNDERCOVERS
    allow_blank = ALLOW_BLANK
    if text:
        parts = text.split()
        for t in parts:
            if t.isdigit():
                undercovers = max(1, min(3, int(t)))
            elif t.lower() in ("blank", "白板", "yes"):
                allow_blank = True
            elif t.lower() in ("noblank", "无白板", "no"):
                allow_blank = False

    games[gid] = Game(group_id=gid, owner_id=uid, allow_blank=allow_blank)
    bot = get_bot()
    nick = await get_nickname(bot, gid, uid)
    games[gid].players[uid] = Player(uid=uid, nickname=nick)

    show_role = await get_group_show_role(gid)
    await cmd_open.finish(
        f"🎮 谁是卧底开局成功！房主：" + ms_at(uid) + "\n"
        f"— 输入「/加入」参与（至少{MIN_PLAYERS}人，上限{MAX_PLAYERS}）\n"
        f"— 房主「/发身份 {undercovers}{' blank' if allow_blank else ' noblank'}」开始\n"
        f"— 发言：轮到谁谁直接说一句，系统自动切到下一位；最后一位说完自动进入投票\n"
        f"— 投票：私聊回复数字（0=弃权，数字=投序号）\n"
        f"— 当前私聊是否显示身份：{'开' if show_role else '关'}（用「身份提示 开/关」可修改，群管）"
    )

@cmd_join.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    uid = event.user_id
    if gid not in games:
        await cmd_join.finish("⚠️ 还没有开局。用「卧底开局」来创建。")
    game = games[gid]
    if game.ready:
        await cmd_join.finish("⚠️ 已经开始发身份了，不能再加入。")
    if uid in game.players:
        await cmd_join.finish("你已经在房间里啦~")
    if len(game.players) >= MAX_PLAYERS:
        await cmd_join.finish(f"⚠️ 人满为患（上限{MAX_PLAYERS}）。")

    bot = get_bot()
    nick = await get_nickname(bot, gid, uid)
    game.players[uid] = Player(uid=uid, nickname=nick)
    await cmd_join.finish(f"✅ 加入成功！当前人数：{len(game.players)}")

@cmd_quit.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    uid = event.user_id
    if gid not in games:
        await cmd_quit.finish("⚠️ 本群没有正在筹备的房间。")
    game = games[gid]
    if game.ready:
        await cmd_quit.finish("⚠️ 游戏已开始，不能退出（你可以被票出😈）。")
    if uid not in game.players:
        await cmd_quit.finish("你不在房间里哦。")
    if uid == game.owner_id:
        await cmd_quit.finish("⚠️ 房主不能在开始前退出。如需取消请「结束卧底」。")
    del game.players[uid]
    await cmd_quit.finish(f"已退出。当前人数：{len(game.players)}")

@cmd_start.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    gid = event.group_id
    uid = event.user_id
    if gid not in games:
        await cmd_start.finish("⚠️ 还没有开局。用「卧底开局」来创建。")
    game = games[gid]
    if uid != game.owner_id:
        await cmd_start.finish("只有房主可以开始发身份。")
    if game.ready:
        await cmd_start.finish("已经开始过了。")
    n = len(game.players)
    if n < MIN_PLAYERS:
        await cmd_start.finish(f"⚠️ 人数不足（至少{MIN_PLAYERS}人）。当前{n}人。")
    if not WORD_BANK:
        await cmd_start.finish(f"⚠️ 词库为空。请先准备 JSON（例如 {WORD_FILE}）并用「重载词库」加载。")

    text = arg.extract_plain_text().strip()
    undercover_count = DEFAULT_UNDERCOVERS
    use_blank = game.allow_blank
    if text:
        parts = text.split()
        for t in parts:
            if t.isdigit():
                undercover_count = max(1, min(3, int(t)))
            elif t.lower() in ("blank", "白板", "yes"):
                use_blank = True
            elif t.lower() in ("noblank", "无白板", "no"):
                use_blank = False
    if undercover_count >= n:
        undercover_count = max(1, n // 3)

    assign_roles(game, undercover_count, use_blank)
    game.ready = True
    game.reset_round_flags()

    await add_plays(gid, list(game.players.keys()), 1)

    show_role = await get_group_show_role(gid)

    bot = get_bot()
    for p in game.players.values():
        if p.is_undercover:
            word = game.word_undercover
            role = "卧底"
        elif p.is_blank:
            word = "（空白）"
            role = "白板"
        else:
            word = game.word_civilian
            role = "平民"
        try:
            if show_role:
                msg = f"你是【{role}】。\n你的词语：{word}\n请低调发言，别暴露😏"
            else:
                msg = f"你的词语：{word}\n请低调发言，别暴露😏"
            await bot.send_private_msg(user_id=p.uid, message=msg)
        except Exception:
            pass

    order_names = " → ".join([game.players[x].nickname for x in game.alive_order])
    first = game.players[current_alive_order(game)[0]].nickname
    await cmd_start.finish(
        "🎉 词语已发出，游戏开始！\n"
        f"本轮发言顺序（随机）：\n{order_names}\n"
        f"规则：轮到谁谁【直接发一句话】即可，系统自动切到下一位；最后一位说完自动进入投票。\n"
        f"现在请 {first} 开始发言。"
    )

@cmd_status.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid not in games:
        await cmd_status.finish("本群暂无卧底房间。")
    game = games[gid]
    txt = (
        f"局势：\n"
        f"- 回合：{game.round_no}\n"
        f"- 存活：{len(game.alive_ids())} 人\n"
        f"- 卧底尚存：{game.undercovers_alive()} 人\n"
        f"存活名单（投票序号）：\n{render_alive_numbered(game)}"
    )
    await cmd_status.finish(txt)

@cmd_vote.handle()
async def _(event: GroupMessageEvent, matcher: Matcher):
    await matcher.finish(
        "🔒 本游戏采用【私聊数字投票】以保护隐私。\n"
        "我会在投票阶段私聊你序号列表，请在私聊直接回复数字：\n"
        "  0 = 弃权； 其他数字 = 投给该序号的玩家（若未收到私聊可先加好友或用「状态」查看序号）。"
    )

@cmd_review.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    if gid not in games:
        await cmd_review.finish("本群暂无卧底房间。")
    game = games[gid]
    if not game.history:
        await cmd_review.finish("还没有可复盘的记录。")
    lines = "\n".join(game.history[-50:])
    if game.ready:
        lines = re.sub(r"（(卧底|平民|白板)）", "（身份保密）", lines)
    await cmd_review.finish(f"📜 本局复盘（最近50条）：\n{lines}")

@cmd_words.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    gid = event.group_id
    uid = event.user_id
    if gid not in games:
        await cmd_words.finish("先「卧底开局」再自定义词。")
    game = games[gid]
    if uid != game.owner_id:
        await cmd_words.finish("只有房主能自定义词。")
    if game.ready:
        await cmd_words.finish("已经开始发身份，无法再改词。")

    text = arg.extract_plain_text().strip()
    if "|" not in text:
        await cmd_words.finish("格式：/自定义词 平民词|卧底词")
    civ, uc = [x.strip() for x in text.split("|", 1)]
    if not civ or not uc:
        await cmd_words.finish("词语不能为空。")
    WORD_BANK.insert(0, (civ, uc))
    await cmd_words.finish(f"✅ 已加入自定义词：{civ} | {uc}（仅当前进程有效；如需长期使用请写入 {WORD_FILE}）")

@cmd_reload_words.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    path = arg.extract_plain_text().strip() or WORD_FILE
    n = load_words_from_json(path)
    if n > 0:
        await cmd_reload_words.finish(f"✅ 已从 {path} 加载 {n} 对词。当前可用词对：{len(WORD_BANK)}")
    else:
        await cmd_reload_words.finish(f"⚠️ 未从 {path} 加载到新词（文件不存在或格式不正确）。当前可用词对：{len(WORD_BANK)}")

@cmd_end.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    uid = event.user_id
    if gid not in games:
        await cmd_end.finish("本群没有卧底房间。")
    game = games[gid]
    if uid != game.owner_id:
        await cmd_end.finish("只有房主可以结束本局。")
    del games[gid]
    await cmd_end.finish("🧹 已清理本局。欢迎随时「卧底开局」。")

# ===================== 配置 & 排行 指令实现 =====================
@cmd_role_hint.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    gid = event.group_id
    text = arg.extract_plain_text().strip()
    bot = get_bot()

    if not text:
        cur = await get_group_show_role(gid)
        await cmd_role_hint.finish(f"当前设置：{'显示身份' if cur else '不显示身份'}（在私聊发词时）\n用法：身份提示 开 / 身份提示 关")
        return

    # 仅群主/管理员可修改
    try:
        info = await bot.get_group_member_info(group_id=gid, user_id=event.user_id, no_cache=True)
        role = (info.get("role") or "").lower()
    except Exception:
        role = "member"
    if role not in ("owner", "admin"):
        await cmd_role_hint.finish("⚠️ 只有群主/管理员可以修改该设置。可不带参数查询当前状态。")

    v = text.lower()
    if v in ("开", "on", "true", "1", "是", "开启"):
        await set_group_show_role(gid, True)
        await cmd_role_hint.finish("✅ 已开启：私聊会附带身份（平民/卧底/白板）。")
    elif v in ("关", "off", "false", "0", "否", "关闭"):
        await set_group_show_role(gid, False)
        await cmd_role_hint.finish("✅ 已关闭：私聊只发词语，不提示身份。")
    else:
        await cmd_role_hint.finish("用法：身份提示 开 / 身份提示 关（或直接发送“身份提示”查看当前状态）")

@cmd_rank.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    top = await get_top_wins(gid, topn=10)
    if not top:
        await cmd_rank.finish("本群还没有胜场记录哦～快开一局吧！")
    bot = get_bot()
    lines = ["🏆 本群胜场榜（前10）:"]
    for i, (uid, wins) in enumerate(top, start=1):
        name = await get_nickname(bot, gid, uid)
        lines.append(f"{i}. {name}（{uid}）— {wins} 胜")
    await cmd_rank.finish("\n".join(lines))

@cmd_mywins.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    uid = event.user_id
    wins = await get_wins(gid, uid)
    await cmd_mywins.finish(f"你在本群共有 {wins} 场胜利。")

@cmd_reset_rank.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    bot = get_bot()
    try:
        info = await bot.get_group_member_info(group_id=gid, user_id=event.user_id, no_cache=True)
        role = (info.get("role") or "").lower()
    except Exception:
        role = "member"
    if role not in ("owner", "admin"):
        await cmd_reset_rank.finish("⚠️ 只有群主/管理员可以重置排行榜。")
    await reset_group_wins(gid)
    await cmd_reset_rank.finish("🧹 已重置本群的胜场排行榜。")

# ===================== 私聊数字投票拦截器 =====================
def _is_waiting_pm_vote(event) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    uid = event.user_id
    text = str(event.get_plaintext() or "").strip()
    if not text.isdigit():
        return False
    for g in games.values():
        if g.ready and uid in g.players and g.players[uid].is_alive:
            if uid in g.expecting_pm_vote and g.vote_round_tag == g.round_no:
                return True
    return False

pm_numeric_vote = on_message(rule=Rule(_is_waiting_pm_vote), priority=8, block=True)

@pm_numeric_vote.handle()
async def _(event: PrivateMessageEvent, matcher: Matcher):
    uid = event.user_id
    text = event.get_plaintext().strip()
    num = int(text)

    game: Optional[Game] = None
    for g in games.values():
        if g.ready and uid in g.players and g.players[uid].is_alive and uid in g.expecting_pm_vote and g.vote_round_tag == g.round_no:
            game = g
            break
    if not game:
        await matcher.finish("当前没有等待你投票的对局。")

    bot = get_bot()

    idx_map = build_index_map(game)
    inv = {idx: u for idx, u in idx_map.items()}

    if num == 0:
        async with game.lock:
            if uid in game.votes:
                await matcher.finish("你本轮已经投过票了，不能更改。")
            if not all(p.has_spoken_this_round for p in game.alive_players()):
                await matcher.finish("仍在发言阶段，暂不可弃权。")
            game.votes[uid] = None
            all_done = set(game.votes.keys()) >= set(game.alive_ids())
        if all_done:
            await settle_and_announce(bot, game)
        return

    if num not in inv:
        tips = (
            "❌ 序号不存在。请回复列表中的【数字】，或回复 0 弃权。\n"
            "当前存活（投票序号）：\n" + render_alive_numbered(game)
        )
        await matcher.finish(tips)

    target_uid = inv[num]

    async with game.lock:
        if uid in game.votes:
            await matcher.finish("你本轮已经投过票了，不能更改。")
        if not all(p.has_spoken_this_round for p in game.alive_players()):
            await matcher.finish("仍在发言阶段，暂不可投票。")
        if target_uid not in game.players or not game.players[target_uid].is_alive:
            await matcher.finish("目标不在游戏或已出局。")
        game.votes[uid] = target_uid
        voted_name = game.players[target_uid].nickname
        all_done = set(game.votes.keys()) >= set(game.alive_ids())

    await matcher.send(f"✅ 已记录你对「{voted_name}」的投票。")
    if all_done:
        await settle_and_announce(bot, game)

@cmd_help.handle()
async def _(event: GroupMessageEvent):
    msg = (
        "🎮 谁是卧底 - 群聊版玩法说明\n"
        "——————————\n"
        "【开局】\n"
        "卧底开局 [卧底人数] [blank]  → 创建房间（可选参数：卧底人数，blank=有白板）\n"
        "加入   → 进入房间\n"
        "发身份 → 房主开始游戏并私聊词语\n"
        "\n"
        "【发言阶段】\n"
        "- 系统会在群里公布发言顺序\n"
        "- 轮到谁，谁直接在群里说一句描述\n"
        "- 每人一句话，依次发完自动进入投票\n"
        "\n"
        "【投票阶段（私聊进行）】\n"
        "- 机器人私聊存活玩家投票序号列表\n"
        "- 私聊直接回复数字：0=弃权，数字=投票对象\n"
        "\n"
        "【胜负判定】\n"
        "- 卧底全出局 → 平民胜利\n"
        "- 卧底数≥平民数 → 卧底胜利\n"
        "\n"
        "【常用指令】\n"
        "状态   → 查看当前局势和投票序号\n"
        "复盘   → 查看上一局记录\n"
        "结束卧底 → 强制结束当前局\n"
        "身份提示 开/关 → 设置私聊是否提示身份\n"
        "卧底帮助 → 查看本说明\n"
        "胜率榜 / 我的胜率 → 查看胜率\n"
    )
    await cmd_help.finish(msg)
    
@cmd_winrate.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    async with _store_lock:
        g = stats_store.get("groups", {}).get(str(gid), {})
        wins_map = g.get("wins", g)  # 兼容旧
        plays_map = g.get("plays", {})
        uids = set(uid for uid in wins_map.keys() if uid.isdigit()) | set(uid for uid in plays_map.keys() if uid.isdigit())

    if not uids:
        await cmd_winrate.finish("本群还没有统计数据哦～先来一局吧！")

    table = []
    for uid_s in uids:
        w = int(wins_map.get(uid_s, 0))
        p = int(plays_map.get(uid_s, 0))
        if p <= 0:
            continue
        rate = w / p
        table.append((int(uid_s), w, p, rate))

    if not table:
        await cmd_winrate.finish("还没有可计算胜率的数据。")

    # 排序：胜率↓，参与局数↓，胜场↓，UID↑
    table.sort(key=lambda x: (-x[3], -x[2], -x[1], x[0]))
    top = table[:10]

    bot = get_bot()
    lines = ["📈 本群胜率榜（前10）:"]
    for i, (uid, w, p, rate) in enumerate(top, start=1):
        name = await get_nickname(bot, gid, uid)
        lines.append(f"{i}. {name}（{uid}）— 胜率 {rate*100:.2f}%（{w}/{p}）")
    await cmd_winrate.finish("\n".join(lines))

@cmd_mywinrate.handle()
async def _(event: GroupMessageEvent):
    gid = event.group_id
    uid = event.user_id
    w = await get_wins(gid, uid)
    p = await get_plays(gid, uid)
    if p <= 0:
        await cmd_mywinrate.finish("你还没有参与过统计的对局。")
    else:
        await cmd_mywinrate.finish(f"你的胜率：{(w/p)*100:.2f}%（{w}/{p}，胜/局）")
