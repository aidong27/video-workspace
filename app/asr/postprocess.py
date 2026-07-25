from __future__ import annotations

import re

from app.asr.base import TranscriptSegment


def normalize_segments(
    segments: list[TranscriptSegment],
    *,
    max_chars: int = 42,
    minimum_duration_ms: int = 500,
) -> list[TranscriptSegment]:
    cleaned: list[TranscriptSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start_ms, item.end_ms)):
        text = re.sub(r"\s+", " ", segment.text).strip()
        if not text:
            continue
        start = max(0, int(segment.start_ms))
        end = max(start + minimum_duration_ms, int(segment.end_ms))
        candidate = TranscriptSegment(
            start_ms=start,
            end_ms=end,
            text=text,
            speaker=segment.speaker,
            emotion=segment.emotion,
            words=segment.words,
        )
        if cleaned:
            previous = cleaned[-1]
            overlap = min(previous.end_ms, candidate.end_ms) - max(previous.start_ms, candidate.start_ms)
            if overlap > 0 and previous.text == candidate.text:
                cleaned[-1] = TranscriptSegment(
                    start_ms=min(previous.start_ms, candidate.start_ms),
                    end_ms=max(previous.end_ms, candidate.end_ms),
                    text=previous.text,
                    speaker=previous.speaker,
                    emotion=previous.emotion,
                    words=previous.words or candidate.words,
                )
                continue
        cleaned.extend(_split_segment(candidate, max_chars=max_chars))
    return _remove_timeline_overlaps(cleaned, minimum_duration_ms)


def _split_segment(segment: TranscriptSegment, *, max_chars: int) -> list[TranscriptSegment]:
    if len(segment.text) <= max_chars or segment.end_ms - segment.start_ms < 1200:
        return [segment]
    parts = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])", segment.text)
        if part.strip()
    ]
    if len(parts) == 1:
        parts = [segment.text[index : index + max_chars] for index in range(0, len(segment.text), max_chars)]
    else:
        packed: list[str] = []
        current = ""
        for part in parts:
            if current and len(current) + len(part) > max_chars:
                packed.append(current)
                current = part
            else:
                current += part
        if current:
            packed.append(current)
        parts = packed
    if len(parts) <= 1:
        return [segment]
    total_chars = sum(len(part) for part in parts)
    duration = segment.end_ms - segment.start_ms
    cursor = segment.start_ms
    output: list[TranscriptSegment] = []
    consumed = 0
    for index, part in enumerate(parts):
        consumed += len(part)
        end = segment.end_ms if index == len(parts) - 1 else segment.start_ms + round(duration * consumed / total_chars)
        output.append(
            TranscriptSegment(
                start_ms=cursor,
                end_ms=max(cursor + 1, end),
                text=part,
                speaker=segment.speaker,
                emotion=segment.emotion,
                words=segment.words if len(parts) == 1 else (),
            )
        )
        cursor = end
    return output


def _remove_timeline_overlaps(
    segments: list[TranscriptSegment],
    minimum_duration_ms: int,
) -> list[TranscriptSegment]:
    output: list[TranscriptSegment] = []
    for item in segments:
        start = item.start_ms
        if output and start < output[-1].end_ms:
            previous = output[-1]
            midpoint = max(previous.start_ms + 1, (start + previous.end_ms) // 2)
            output[-1] = TranscriptSegment(
                start_ms=previous.start_ms,
                end_ms=midpoint,
                text=previous.text,
                speaker=previous.speaker,
                emotion=previous.emotion,
                words=previous.words,
            )
            start = midpoint
        end = max(start + minimum_duration_ms, item.end_ms)
        output.append(
            TranscriptSegment(
                start_ms=start,
                end_ms=end,
                text=item.text,
                speaker=item.speaker,
                emotion=item.emotion,
                words=item.words,
            )
        )
    return output
