"""无需外部素材的轻量游戏音效。"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Dict, Iterable, Tuple

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QObject, QUrl
from PyQt5.QtMultimedia import (
    QAudioDeviceInfo,
    QAudioFormat,
    QAudioOutput,
    QMediaContent,
    QMediaPlayer,
)


class GameSoundPlayer(QObject):
    """在 Qt 音频线程中播放短促提示音，不阻塞 GUI 和直播监听。"""

    SAMPLE_RATE = 44100

    def __init__(
        self,
        enabled: bool = True,
        parent=None,
        custom_sounds: Dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.enabled = bool(enabled)
        self.audio_output = None
        self._active_buffer = None
        self._clips: Dict[str, QByteArray] = {}
        self._custom_sounds = {
            name: str(path)
            for name, path in (custom_sounds or {}).items()
            if name in {"add", "remove", "eat", "gift"} and str(path)
        }
        self.media_player = None
        # 用户关闭音效时不要再查询 Windows 音频设备，启动会更快，也避免
        # 无音频设备的推流机在初始化阶段等待驱动超时。
        if not self.enabled:
            return

        # 自定义音频交给系统媒体后端播放，支持常见 WAV/MP3/OGG/M4A。
        self.media_player = QMediaPlayer(self)
        self.media_player.setVolume(35)

        audio_format = QAudioFormat()
        audio_format.setSampleRate(self.SAMPLE_RATE)
        audio_format.setChannelCount(1)
        audio_format.setSampleSize(16)
        audio_format.setCodec("audio/pcm")
        audio_format.setByteOrder(QAudioFormat.LittleEndian)
        audio_format.setSampleType(QAudioFormat.SignedInt)

        device = QAudioDeviceInfo.defaultOutputDevice()
        if device.isNull() or not device.isFormatSupported(audio_format):
            # 没有输出设备时静默禁用，不能影响游戏启动。
            return

        self.audio_output = QAudioOutput(device, audio_format, self)
        self.audio_output.setVolume(0.24)
        self._clips = {
            "add": self._make_clip(((540, 0.045), (760, 0.075)), 0.38),
            "remove": self._make_clip(((420, 0.050), (300, 0.080)), 0.34),
            "eat": self._make_clip(((230, 0.045), (170, 0.055), (620, 0.070)), 0.34),
            "gift": self._make_clip(((660, 0.045), (900, 0.050), (1220, 0.095)), 0.32),
        }

    def _make_clip(
        self,
        notes: Iterable[Tuple[float, float]],
        volume: float,
    ) -> QByteArray:
        pcm = bytearray()
        for frequency, duration in notes:
            sample_count = max(1, int(self.SAMPLE_RATE * duration))
            attack = max(1, int(self.SAMPLE_RATE * 0.006))
            release = max(1, int(self.SAMPLE_RATE * min(0.025, duration * 0.42)))
            for index in range(sample_count):
                envelope = min(
                    1.0,
                    index / attack,
                    (sample_count - index - 1) / release,
                )
                phase = 2.0 * math.pi * frequency * index / self.SAMPLE_RATE
                # 少量二次谐波让短音在直播压缩后仍能听清，但保持柔和。
                wave = math.sin(phase) * 0.82 + math.sin(phase * 2.0) * 0.18
                sample = int(32767 * volume * max(0.0, envelope) * wave)
                pcm.extend(struct.pack("<h", max(-32768, min(32767, sample))))
            pcm.extend(b"\x00\x00" * int(self.SAMPLE_RATE * 0.006))
        return QByteArray(bytes(pcm))

    def play(self, name: str) -> None:
        """播放指定提示音；连续触发时以最新事件为准。"""
        if not self.enabled:
            return
        custom_path = self._custom_sounds.get(name, "")
        if custom_path and Path(custom_path).is_file() and self.media_player is not None:
            if self.audio_output is not None:
                self.audio_output.stop()
            self.media_player.stop()
            self.media_player.setMedia(
                QMediaContent(QUrl.fromLocalFile(str(Path(custom_path).resolve())))
            )
            self.media_player.play()
            return
        if self.audio_output is None or name not in self._clips:
            return
        if self.media_player is not None:
            self.media_player.stop()
        self.audio_output.stop()
        if self._active_buffer is not None:
            self._active_buffer.close()
            self._active_buffer.deleteLater()
        buffer = QBuffer(self)
        buffer.setData(self._clips[name])
        if not buffer.open(QIODevice.ReadOnly):
            buffer.deleteLater()
            return
        self._active_buffer = buffer
        self.audio_output.start(buffer)

    def stop(self) -> None:
        """停止试听或游戏音效，供运行中切换配置时安全释放。"""
        if self.media_player is not None:
            self.media_player.stop()
        if self.audio_output is not None:
            self.audio_output.stop()
        if self._active_buffer is not None:
            self._active_buffer.close()
            self._active_buffer.deleteLater()
            self._active_buffer = None
