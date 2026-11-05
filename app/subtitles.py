"""Subtitle entry model, parsers for platform/track formats, and renderers.

Parsing accepts Bilibili/Douyin JSON bodies, SRT and WebVTT. Rendering turns
normalized entries into TXT, SRT, VTT, Markdown or JSON so a cached result can
be exported in any format without repeating recognition.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

from .errors import ExtractionFailure

OUTPUT_FORMATS = ("txt", "srt", "vtt", "markdown", "json")


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str


def deserialize_entries(items: Any) -> list[SubtitleEntry]:
    if not isinstance(items, list):
        return []
    entries: list[SubtitleEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            text = str(item.get("text") or "").strip()
            start = float(item.get("start") or 0)
            end = float(item.get("end") or 0)
            if text and math.isfinite(start) and math.isfinite(end):
                entries.append(SubtitleEntry(start, end, text))
        except (TypeError, ValueError, OverflowError):
            continue
    return entries


def parse_json_subtitle(text: str) -> list[SubtitleEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionFailure(502, "Subtitle JSON could not be parsed.", "subtitle_parse_failed") from exc
    body: Any = None
    millisecond_times = False
    if isinstance(data, dict):
        body = data.get("body")
        if not isinstance(body, list):
            body = data.get("utterances")
            millisecond_times = isinstance(body, list)
        if not isinstance(body, list) and isinstance(data.get("data"), dict):
            body = data["data"].get("utterances") or data["data"].get("body")
            millisecond_times = isinstance(data["data"].get("utterances"), list)
    elif isinstance(data, list):
        body = data
    if not isinstance(body, list):
        raise ExtractionFailure(502, "字幕 JSON 中没有可识别的字幕列表。", "subtitle_parse_failed")
    entries: list[SubtitleEntry] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        start = item.get("from", item.get("start", item.get("start_time", 0)))
        end = item.get("to", item.get("end", item.get("end_time", start)))
        content = item.get("content", item.get("text", ""))
        try:
            start_value = float(start)
            end_value = float(end)
            if millisecond_times or "start_time" in item or "end_time" in item:
                start_value /= 1000
                end_value /= 1000
            entries.append(SubtitleEntry(start_value, end_value, str(content).strip()))
        except (TypeError, ValueError):
            continue
    return [e for e in entries if e.text]


def subtitle_time_to_seconds(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        raise ValueError("invalid subtitle timecode")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


SUBTITLE_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})(?:\s+.*)?$"
)


def parse_timed_subtitle(text: str) -> list[SubtitleEntry]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    entries: list[SubtitleEntry] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines or lines[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((index for index, line in enumerate(lines[:3]) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = SUBTITLE_TIMING_RE.search(lines[timing_index])
        if not match:
            continue
        caption = "\n".join(lines[timing_index + 1 :]).strip()
        if not caption:
            continue
        try:
            entries.append(
                SubtitleEntry(
                    subtitle_time_to_seconds(match.group("start")),
                    subtitle_time_to_seconds(match.group("end")),
                    caption,
                )
            )
        except ValueError:
            continue
    if not entries:
        raise ExtractionFailure(502, "字幕文件中没有可识别的时间轴。", "subtitle_parse_failed")
    return entries


def parse_subtitle_text(text: str, ext: str) -> list[SubtitleEntry]:
    normalized_ext = (ext or "").lower()
    if normalized_ext == "json":
        return parse_json_subtitle(text)
    if normalized_ext in {"srt", "vtt", "webvtt"}:
        return parse_timed_subtitle(text)
    raise ExtractionFailure(502, f"暂不支持转换 {normalized_ext or 'unknown'} 字幕格式。", "unsupported_subtitle_format")


def seconds_to_srt(value: float) -> str:
    ms_total = max(0, int(round(value * 1000)))
    hours, rem = divmod(ms_total, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def seconds_to_vtt(value: float) -> str:
    return seconds_to_srt(value).replace(",", ".")


def render_entries(entries: list[SubtitleEntry], output_format: str, meta: dict[str, Any]) -> str:
    fmt = "markdown" if output_format == "md" else output_format
    if fmt == "json":
        payload = {
            "metadata": meta,
            "entries": [{"start": e.start, "end": e.end, "text": e.text} for e in entries],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt == "txt":
        return "\n".join(e.text for e in entries) + "\n"
    if fmt == "markdown":
        lines = [f"# {meta.get('title') or 'Video Subtitle'}", ""]
        note = meta.get("note") or meta.get("warning")
        if note:
            lines.extend([f"> {note}", ""])
        for e in entries:
            lines.append(f"- `{seconds_to_vtt(e.start)}` {e.text}")
        return "\n".join(lines) + "\n"
    if fmt == "srt":
        blocks = []
        for i, e in enumerate(entries, 1):
            blocks.append(f"{i}\n{seconds_to_srt(e.start)} --> {seconds_to_srt(e.end)}\n{e.text}")
        return "\n\n".join(blocks) + "\n"
    if fmt == "vtt":
        blocks = ["WEBVTT", ""]
        for e in entries:
            blocks.append(f"{seconds_to_vtt(e.start)} --> {seconds_to_vtt(e.end)}\n{e.text}\n")
        return "\n".join(blocks)
    raise ExtractionFailure(400, "Unsupported output format.", "unsupported_format", terminal=True)
