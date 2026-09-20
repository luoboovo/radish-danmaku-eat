"""blivedm 直播弹幕/礼物监听线程。与游戏窗口完全解耦。"""

from __future__ import annotations

import asyncio
import http.cookies
import threading
import time
from typing import Dict

from PyQt5.QtCore import QThread, pyqtSignal


class BiliLiveThread(QThread):
    """在独立线程运行 asyncio，借助 Qt 信号安全通知 GUI 主线程。"""

    status_changed = pyqtSignal(str, str)
    food_delta = pyqtSignal(int, str)
    food_operation = pyqtSignal(str, float, int, str)
    range_triggered = pyqtSignal(int, str)
    activity = pyqtSignal(str)
    gift_effect = pyqtSignal(str, int, str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self.config = dict(config)
        self._stop_requested = threading.Event()
        self._last_trigger_by_user: Dict[str, float] = {}
        self._seen_gift_events: Dict[str, float] = {}

    def request_stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        room_text = str(self.config.get("room_id", "")).strip()
        if not room_text:
            self.status_changed.emit("未配置房间（离线模式）", "offline")
            return
        try:
            asyncio.run(self._run_async(int(room_text)))
        except ModuleNotFoundError as error:
            self.status_changed.emit(
                f"缺少依赖 {error.name}，请执行 pip install -r requirements.txt",
                "error",
            )
        except Exception as error:  # 保证网络线程异常不会带崩 GUI
            self.status_changed.emit(f"监听线程异常：{error}", "error")

    async def _run_async(self, room_id: int) -> None:
        # 延迟导入：即便尚未安装 blivedm，用户仍能启动界面进行离线试玩。
        import aiohttp
        import blivedm
        import blivedm.models.web as web_models

        owner = self

        class StatusClient(blivedm.BLiveClient):
            """在上游客户端自动重连机制之外补充可视状态通知。"""

            async def _on_ws_connect(inner_self) -> None:
                await super()._on_ws_connect()
                if not owner._stop_requested.is_set():
                    owner.status_changed.emit(f"已连接房间 {room_id}", "connected")

            async def _on_ws_close(inner_self) -> None:
                await super()._on_ws_close()
                if not owner._stop_requested.is_set():
                    owner.status_changed.emit("连接中断，正在自动重连…", "reconnecting")

        class GameHandler(blivedm.BaseHandler):
            def _on_danmaku(
                inner_self,
                client: blivedm.BLiveClient,
                message: web_models.DanmakuMessage,
            ) -> None:
                owner._handle_danmaku(message)

            def _on_gift(
                inner_self,
                client: blivedm.BLiveClient,
                message: web_models.GiftMessage,
            ) -> None:
                owner._handle_gift(message)

            def on_client_stopped(self, client, exception) -> None:
                if exception is not None and not owner._stop_requested.is_set():
                    owner.status_changed.emit(
                        f"连接异常：{exception}，5 秒后重试…", "error"
                    )

        cookies = http.cookies.SimpleCookie()
        sessdata = self._extract_sessdata(str(self.config.get("sessdata", "")))
        if sessdata:
            cookies["SESSDATA"] = sessdata
            cookies["SESSDATA"]["domain"] = "bilibili.com"

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if sessdata:
                session.cookie_jar.update_cookies(cookies)
            while not self._stop_requested.is_set():
                self.status_changed.emit(f"正在连接房间 {room_id}…", "info")
                client = StatusClient(room_id, session=session)
                client.set_handler(GameHandler())
                # 上游内置掉线重连；重试间隔上限 30 秒，避免网络恢复后等待过久。
                client.set_reconnect_policy(
                    lambda retry_count, total_retry_count: min(
                        30.0, 1.5 * (2 ** min(retry_count - 1, 4))
                    )
                )
                client.start()
                try:
                    while client.is_running and not self._stop_requested.is_set():
                        await asyncio.sleep(0.2)
                finally:
                    if client.is_running:
                        await client.stop_and_close()
                    else:
                        await client.close()
                if not self._stop_requested.is_set():
                    await self._interruptible_sleep(5.0)

        self.status_changed.emit("监听已停止", "offline")

    async def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop_requested.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.2)

    @staticmethod
    def _extract_sessdata(text: str) -> str:
        """兼容只粘贴值，或误粘贴整段 Cookie 的情况。"""
        text = text.strip()
        if not text:
            return ""
        if "SESSDATA=" not in text:
            return text
        try:
            cookie = http.cookies.SimpleCookie()
            cookie.load(text)
            morsel = cookie.get("SESSDATA")
            return morsel.value if morsel else ""
        except http.cookies.CookieError:
            return ""

    def _can_trigger(self, uid: int, uname: str) -> bool:
        cooldown = float(self.config.get("user_cooldown_seconds", 0.0))
        if cooldown <= 0:
            return True
        key = f"uid:{uid}" if uid else f"name:{uname}"
        now = time.monotonic()
        last = self._last_trigger_by_user.get(key, -1e30)
        if now - last < cooldown:
            return False
        self._last_trigger_by_user[key] = now
        # 长时间运行时清理冷却字典，避免无限增长。
        if len(self._last_trigger_by_user) > 20000:
            cutoff = now - max(60.0, cooldown * 2)
            self._last_trigger_by_user = {
                user: timestamp
                for user, timestamp in self._last_trigger_by_user.items()
                if timestamp >= cutoff
            }
        return True

    def _handle_danmaku(self, message) -> None:
        incoming = str(message.msg).strip()
        case_sensitive = bool(self.config.get("danmaku_case_sensitive", False))
        comparable = incoming if case_sensitive else incoming.casefold()
        mode = self.config.get("danmaku_match_mode", "exact")
        delta = 0
        for rule in self.config.get("danmaku_rules", []):
            keyword = str(rule.get("keyword", "")).strip()
            target = keyword if case_sensitive else keyword.casefold()
            matched = comparable == target if mode == "exact" else target in comparable
            if matched:
                delta += int(rule.get("delta", 0))
        if delta == 0 or not self._can_trigger(int(message.uid), str(message.uname)):
            return
        # 结构化文本交给 GUI 生成多条可滚动互动日志。
        self.activity.emit(
            f"danmaku\t{message.uname}\t{incoming}\t{delta}"
        )
        source = f"弹幕 {message.uname}：{incoming}"
        self.food_delta.emit(delta, source)

    def _handle_gift(self, message) -> None:
        gift_name = str(message.gift_name).strip()
        gift_num = max(1, int(message.num))
        # 连送礼物可能表现为短时间内多条 num=1 的独立消息，不能套用弹幕
        # 防刷冷却，否则“送 10 个”只会结算第 1 个。这里只按交易 ID 去重，
        # 避免断线重连或新旧礼物协议同时推送同一交易时重复结算。
        if self._gift_is_duplicate(message):
            return
        # 所有礼物都进入日志，即便它没有绑定食物或范围规则。
        self.activity.emit(
            f"gift\t{message.uname}\t{gift_name}\t{gift_num}"
        )
        food_rules = [
            rule
            for rule in self.config.get("gift_food_rules", [])
            if str(rule.get("gift_name", "")).strip() == gift_name
        ]
        durations = [
            int(rule.get("seconds", 0))
            for rule in self.config.get("gift_range_rules", [])
            if str(rule.get("gift_name", "")).strip() == gift_name
        ]
        duration = max(durations, default=0)
        if not food_rules and duration <= 0:
            return
        source = f"礼物 {message.uname}：{gift_name}×{gift_num}"
        effect_parts = []
        for rule in food_rules:
            operation = str(rule.get("operation", "add"))
            value = float(rule.get("value", 1.0))
            self.food_operation.emit(
                operation,
                value,
                gift_num,
                source,
            )
            effect_parts.append(self._gift_effect_text(operation, value, gift_num))
        if duration > 0:
            # 一条消息中的 num 可能代表连送多个，范围时长也应按数量累计。
            total_duration = min(86400, duration * gift_num)
            self.range_triggered.emit(total_duration, source)
            effect_parts.append(f"范围拾取 {total_duration} 秒")
        self.gift_effect.emit(gift_name, gift_num, " · ".join(effect_parts))

    @staticmethod
    def _gift_effect_text(operation: str, value: float, quantity: int) -> str:
        """把礼物运算转换为观众能直接看懂的浮窗文字。"""
        if operation in {"add", "subtract"}:
            total = int(round(value * quantity))
            action = "投喂" if operation == "add" else "减少"
            return f"{action} {total} 个"
        if operation == "clear":
            return "清空食物"
        if operation == "wind":
            if quantity > 1:
                return f"刮大风 {quantity} 次 · 随机增减 10%～50%"
            return "刮大风 · 随机增减 10%～50%"
        number = f"{value:g}"
        action = "×" if operation == "multiply" else "÷"
        if quantity > 1:
            return f"食物连续 {action}{number}（{quantity} 次）"
        return f"食物 {action}{number}"

    def _gift_is_duplicate(self, message) -> bool:
        """仅用 B 站礼物交易 ID 去重，不吞掉同一用户的连续合法礼物。"""
        transaction_id = str(
            getattr(message, "tid", "") or getattr(message, "rnd", "") or ""
        ).strip()
        if not transaction_id:
            # 旧消息缺少交易 ID 时宁可正常计数，也不能误伤连续礼物。
            return False
        key = ":".join(
            (
                str(getattr(message, "uid", 0)),
                str(getattr(message, "gift_id", 0)),
                transaction_id,
            )
        )
        now = time.monotonic()
        last_seen = self._seen_gift_events.get(key)
        if last_seen is not None and now - last_seen < 300.0:
            return True
        self._seen_gift_events[key] = now
        if len(self._seen_gift_events) > 10000:
            cutoff = now - 300.0
            self._seen_gift_events = {
                event: timestamp
                for event, timestamp in self._seen_gift_events.items()
                if timestamp >= cutoff
            }
        return False
