#!/usr/bin/env python3
"""JudoIQ - produkcyjny analizator geometryczny."""

from __future__ import annotations

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
VIDEOS_DIR = ROOT / "videos"
REPORTS_DIR = ROOT / "outputs" / "raporty"
VIDEO_OUT_DIR = ROOT / "outputs" / "wideo"
VIDEO_EXT = {".mp4", ".mov", ".avi"}

MODEL_NAME = "yolov8n-pose.pt"
MODEL_CANDIDATES = (
    ROOT / "models" / MODEL_NAME,
    ROOT / MODEL_NAME,
    PROJECT_ROOT / MODEL_NAME,
    Path(MODEL_NAME),
)
CONF = 0.45
MIN_KPT_CONF = 0.35

BLUE_LOW = np.array([90, 70, 40], dtype=np.uint8)
BLUE_HIGH = np.array([130, 255, 255], dtype=np.uint8)
WHITE_V_MIN = 170
WHITE_S_MAX = 70
JUDOGI_RATIO_MIN = 0.30

CONTACT_IOU_THRESHOLD = 0.05
STANDING_FIGHTER_AR_MAX = 0.90
BASELINE_AR_MAX = 0.75
HORIZONTAL_TOTAL_AR = 1.15
TRIGGER_HEIGHT_RATIO = 0.88
TRIGGER_EXPANSION_RATIO = 1.25
TRIGGER_UPWARD_TOP_RATIO = 0.10
TAI_OTOSHI_AR_MIN = 0.80
TAI_OTOSHI_HEIGHT_RATIO = 0.96
TAI_OTOSHI_DROP_RATIO = 0.04
SINGLE_OCCLUSION_DROP_RATIO = 0.18
SINGLE_OCCLUSION_HEIGHT_RATIO = 0.93
SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT = 300
FINAL_HEIGHT_RATIO = 0.95
FINAL_COMPACT_HEIGHT_RATIO = 0.75
FINAL_DROP_RATIO = 0.30
FINAL_SUCCESS_DROP_RATIO = 0.28
FINAL_BIG_BODY_DROP_RATIO = 0.22
RECENT_CONTACT_SECONDS = 0.50

COLOR_P1 = (80, 220, 100)
COLOR_P2 = (100, 180, 255)
ALERT_COLOR = (0, 0, 255)
HUD_COLOR = (0, 255, 255)

SKELETON = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
)


@dataclass
class Fighter:
    label: str
    keypoints: np.ndarray
    bbox: tuple[int, int, int, int]
    area: float

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    @property
    def aspect(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return float(max(x2 - x1, 1) / max(y2 - y1, 1))


@dataclass
class CombinedBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(self.x2 - self.x1, 1)

    @property
    def height(self) -> int:
        return max(self.y2 - self.y1, 1)

    @property
    def aspect(self) -> float:
        return float(self.width / self.height)


@dataclass
class Stats:
    tachiwaza_time: float = 0.0
    newaza_time: float = 0.0
    total_attacks: int = 0
    successful_throws: int = 0
    failed_throws: int = 0
    events: list[str] = field(default_factory=list)


@dataclass
class AttackWindow:
    active: bool = False
    cooldown_until: int = -1
    frame_counter: int = 0
    start_time: float = 0.0
    baseline_top: int = 0
    baseline_height: int = 0
    max_top_drop: int = 0
    max_ar: float = 0.0
    min_height: int = 0

    def start(self, start_time: float, baseline_top: int, baseline_height: int) -> None:
        self.active = True
        self.frame_counter = 0
        self.start_time = start_time
        self.baseline_top = baseline_top
        self.baseline_height = baseline_height
        self.max_top_drop = 0
        self.max_ar = 0.0
        self.min_height = baseline_height

    def finish(self, frame_i: int, cooldown_size: int) -> None:
        self.active = False
        self.cooldown_until = frame_i + cooldown_size
        self.frame_counter = 0
        self.start_time = 0.0
        self.baseline_top = 0
        self.baseline_height = 0
        self.max_top_drop = 0
        self.max_ar = 0.0
        self.min_height = 0


def find_video() -> Path:
    videos = sorted(p for p in VIDEOS_DIR.iterdir() if p.suffix.lower() in VIDEO_EXT)
    if not videos:
        raise FileNotFoundError(f"Brak pliku wideo w {VIDEOS_DIR}")
    return videos[0]


def resolve_model_path() -> str:
    for candidate in MODEL_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return MODEL_NAME


def keypoint_ok(keypoints: np.ndarray, idx: int) -> bool:
    return keypoints.shape[0] > idx and float(keypoints[idx, 2]) >= MIN_KPT_CONF


def is_wearing_judogi(frame: np.ndarray, box) -> bool:
    frame_h, frame_w = frame.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in box)
    x1 = max(0, min(x1, frame_w - 1))
    x2 = max(x1 + 1, min(x2, frame_w))
    y1 = max(0, min(y1, frame_h - 1))
    y2 = max(y1 + 1, min(y2, frame_h))

    box_w = x2 - x1
    box_h = y2 - y1
    tx1 = x1 + int(box_w * 0.15)
    tx2 = x2 - int(box_w * 0.15)
    ty1 = y1 + int(box_h * 0.25)
    ty2 = y1 + int(box_h * 0.70)
    if tx2 <= tx1 or ty2 <= ty1:
        return False

    roi = frame[ty1:ty2, tx1:tx2]
    if roi.size == 0:
        return False

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, BLUE_LOW, BLUE_HIGH)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    white = ((val > WHITE_V_MIN) & (sat < WHITE_S_MAX)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(blue, white)
    return cv2.countNonZero(mask) / max(mask.shape[0] * mask.shape[1], 1) >= JUDOGI_RATIO_MIN


def parse_fighters(frame: np.ndarray, result) -> list[Fighter]:
    if result.boxes is None or result.keypoints is None:
        return []

    boxes = result.boxes.xyxy.cpu().numpy()
    keypoints_all = result.keypoints.data
    fighters: list[Fighter] = []

    for idx, box in enumerate(boxes):
        if idx >= len(keypoints_all):
            break
        if not is_wearing_judogi(frame, box):
            continue

        x1, y1, x2, y2 = (int(v) for v in box)
        area = float(max(x2 - x1, 0) * max(y2 - y1, 0))
        fighters.append(
            Fighter(
                label="?",
                keypoints=keypoints_all[idx].cpu().numpy(),
                bbox=(x1, y1, x2, y2),
                area=area,
            )
        )

    fighters = sorted(fighters, key=lambda f: f.area, reverse=True)[:2]
    fighters.sort(key=lambda f: f.center[0])
    for idx, fighter in enumerate(fighters, start=1):
        fighter.label = f"P{idx}"
    return fighters


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    area_a = max(ax2 - ax1, 0) * max(ay2 - ay1, 0)
    area_b = max(bx2 - bx1, 0) * max(by2 - by1, 0)
    return float(inter / max(area_a + area_b - inter, 1))


def fighters_standing(fighters: list[Fighter]) -> bool:
    return len(fighters) >= 2 and all(f.aspect < STANDING_FIGHTER_AR_MAX for f in fighters[:2])


def get_combined_box(fighters: list[Fighter]) -> Optional[CombinedBox]:
    if not fighters:
        return None
    return CombinedBox(
        x1=min(f.bbox[0] for f in fighters),
        y1=min(f.bbox[1] for f in fighters),
        x2=max(f.bbox[2] for f in fighters),
        y2=max(f.bbox[3] for f in fighters),
    )


def contact_iou(fighters: list[Fighter]) -> Optional[float]:
    if len(fighters) < 2:
        return None
    return bbox_iou(fighters[0].bbox, fighters[1].bbox)


def draw_skeleton(frame: np.ndarray, fighter: Fighter, color: tuple[int, int, int]) -> None:
    kpts = fighter.keypoints
    for i, j in SKELETON:
        if keypoint_ok(kpts, i) and keypoint_ok(kpts, j):
            cv2.line(
                frame,
                (int(kpts[i, 0]), int(kpts[i, 1])),
                (int(kpts[j, 0]), int(kpts[j, 1])),
                color,
                2,
                cv2.LINE_AA,
            )

    x1, y1, x2, y2 = fighter.bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        frame,
        f"{fighter.label} AR:{fighter.aspect:.2f}",
        (x1, max(22, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        color,
        2,
        cv2.LINE_AA,
    )


def draw_combined_box(frame: np.ndarray, combined: Optional[CombinedBox]) -> None:
    if combined is None:
        return
    cv2.rectangle(
        frame,
        (combined.x1, combined.y1),
        (combined.x2, combined.y2),
        ALERT_COLOR,
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"TOTAL AR:{combined.aspect:.2f}",
        (combined.x1, min(combined.y2 + 24, frame.shape[0] - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        ALERT_COLOR,
        2,
        cv2.LINE_AA,
    )


def draw_hud(
    frame: np.ndarray,
    stats: Stats,
    iou: Optional[float],
    total_ar: float,
    frame_counter: int,
    window_size: int,
    baseline_height: int,
    status: str,
    alert: str,
) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (730, 210), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    lines = [
        f"STATUS: {status}",
        f"IoU: {iou:.2f}" if iou is not None else "IoU: ---",
        f"TOTAL AR: {total_ar:.2f}",
        f"OKNO: {frame_counter}/{window_size}",
        f"BASELINE H: {baseline_height}px",
        f"ATAKI: {stats.total_attacks} | RZUTY: {stats.successful_throws} | FAIL: {stats.failed_throws}",
        f"TACHI: {int(stats.tachiwaza_time)}s | NE: {int(stats.newaza_time)}s",
    ]
    for idx, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (18, 36 + idx * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            HUD_COLOR,
            2,
            cv2.LINE_AA,
        )

    if alert:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, h - 72), (w, h), ALERT_COLOR, -1)
        cv2.putText(
            frame,
            alert,
            (20, h - 24),
            cv2.FONT_HERSHEY_DUPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


def write_report(path: Path, video: Path, duration: float, stats: Stats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = max(duration, stats.tachiwaza_time + stats.newaza_time, 0.001)
    lines = [
        "=========================================",
        "          JUDOIQ - RAPORT ANALIZY AI     ",
        "=========================================",
        f"Plik wideo: {video.name}",
        f"Czas trwania nagrania: {duration:.1f} sekund",
        "-----------------------------------------",
        "STATYSTYKI POZYCJI:",
        f"- Czas w stojce: {stats.tachiwaza_time:.1f} sek ({100 * stats.tachiwaza_time / total:.1f}%)",
        f"- Czas w parterze: {stats.newaza_time:.1f} sek ({100 * stats.newaza_time / total:.1f}%)",
        "-----------------------------------------",
        "STATYSTYKI AKCJI:",
        f"- Laczna liczba prob atakow: {stats.total_attacks}",
        f"- Udane rzuty / obalenia: {stats.successful_throws}",
        f"- Nieudane akcje: {stats.failed_throws}",
        "-----------------------------------------",
        "ZDARZENIA:",
    ]
    lines.extend(stats.events or ["  (brak)"])
    lines.extend(["=========================================", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _event_result(raw_event: str) -> Optional[str]:
    if "udany rzut" in raw_event:
        return "successful_throw"
    if "nieudany atak" in raw_event:
        return "failed_attack"
    return None


def _event_time(raw_event: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)s", raw_event)
    return float(match.group(1)) if match else 0.0


def build_analysis_result(
    video_path: Path,
    duration: float,
    stats: Stats,
    annotated_video_path: Path,
    report_path: Path,
) -> dict:
    events = []
    for raw_event in stats.events:
        result = _event_result(raw_event)
        if result is None:
            continue
        events.append(
            {
                "timeSeconds": _event_time(raw_event),
                "type": "attack",
                "result": result,
                "description": raw_event.strip(),
            }
        )

    return {
        "videoName": video_path.name,
        "durationSeconds": duration,
        "tachiwazaSeconds": stats.tachiwaza_time,
        "newazaSeconds": stats.newaza_time,
        "attacks": stats.total_attacks,
        "successfulThrows": stats.successful_throws,
        "failedThrows": stats.failed_throws,
        "annotatedVideoPath": str(annotated_video_path),
        "reportPath": str(report_path),
        "events": events,
    }


def analyze(video_path: Path) -> dict:
    model = YOLO(resolve_model_path())
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Nie mozna otworzyc: {video_path}")

    fps = int(cap.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = 30
    window_size = int(fps * 2.0)
    cooldown_size = int(fps * 3.0)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dt = 1.0 / fps

    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VIDEO_OUT_DIR / f"anotowany_{video_path.stem}.mp4"
    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (frame_w, frame_h),
    )

    stats = Stats()
    attack = AttackWindow()
    baseline_top: Optional[int] = None
    baseline_height: Optional[int] = None
    recent_contact_until = -1
    motion_start_time: Optional[float] = None
    was_touching = False
    last_combined: Optional[CombinedBox] = None
    frame_i = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t = frame_i / fps
        result = model(frame, verbose=False, conf=CONF)[0]
        fighters = parse_fighters(frame, result)
        combined = get_combined_box(fighters)
        if combined is not None:
            last_combined = combined
        total_ar = combined.aspect if combined is not None else 0.0
        iou = contact_iou(fighters)
        if iou is not None and iou > CONTACT_IOU_THRESHOLD:
            recent_contact_until = frame_i + int(fps * RECENT_CONTACT_SECONDS)
        touching = iou is not None and iou > CONTACT_IOU_THRESHOLD
        recently_touching = touching or frame_i <= recent_contact_until
        alert = ""

        if attack.active:
            attack.frame_counter += 1
            if combined is not None:
                attack.max_top_drop = max(attack.max_top_drop, combined.y1 - attack.baseline_top)
                attack.max_ar = max(attack.max_ar, combined.aspect)
                attack.min_height = min(attack.min_height, combined.height)
            if attack.frame_counter >= window_size:
                final_top = combined.y1 if combined is not None else -1
                final_ar = combined.aspect if combined is not None else 0.0
                final_height = combined.height if combined is not None else 0
                final_top_drop = final_top - attack.baseline_top
                final_success = (
                    combined is not None
                    and (
                        final_top_drop > attack.baseline_height * FINAL_SUCCESS_DROP_RATIO
                        or attack.max_top_drop > attack.baseline_height * FINAL_SUCCESS_DROP_RATIO
                        or (
                            attack.baseline_height > SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT
                            and attack.max_top_drop > attack.baseline_height * FINAL_BIG_BODY_DROP_RATIO
                        )
                        or (
                            final_ar > HORIZONTAL_TOTAL_AR
                            and final_height < attack.baseline_height * FINAL_HEIGHT_RATIO
                        )
                        or final_height < attack.baseline_height * FINAL_COMPACT_HEIGHT_RATIO
                    )
                )
                if final_success:
                    stats.successful_throws += 1
                    print(f"{attack.start_time:.1f}s: wykryty atak: udany rzut")
                    stats.events.append(
                        f"  {attack.start_time:.1f}s: wykryty atak: udany rzut "
                        f"(final_top {final_top}px, final_ar {final_ar:.2f}, "
                        f"final_h {final_height}px, max_drop {attack.max_top_drop}px, "
                        f"max_ar {attack.max_ar:.2f}, min_h {attack.min_height}px, "
                        f"baseline_h {attack.baseline_height}px)"
                    )
                    alert = "UDANY RZUT"
                else:
                    print(f"{attack.start_time:.1f}s: wykryty atak: nieudany atak")
                    stats.failed_throws += 1
                    stats.events.append(
                        f"  {attack.start_time:.1f}s: wykryty atak: nieudany atak "
                        f"(final_top {final_top}px, final_ar {final_ar:.2f}, "
                        f"final_h {final_height}px, max_drop {attack.max_top_drop}px, "
                        f"max_ar {attack.max_ar:.2f}, min_h {attack.min_height}px, "
                        f"baseline_h {attack.baseline_height}px)"
                    )
                    alert = "NIEUDANY ATAK"
                attack.finish(frame_i, cooldown_size)
                baseline_top = None
                baseline_height = None
                recent_contact_until = -1
                motion_start_time = None
                was_touching = False
            else:
                alert = "OKNO OCENY RZUTU"
        elif frame_i < attack.cooldown_until:
            alert = "COOLDOWN"
        elif combined is not None and recently_touching:
            attack_started = False
            if baseline_top is not None and baseline_height is not None:
                total_drop = combined.y1 - baseline_top
                height_ratio = combined.height / max(baseline_height, 1)
                horizontal_now = total_ar > HORIZONTAL_TOTAL_AR
                collapsed_now = height_ratio < TRIGGER_HEIGHT_RATIO
                lower_now = total_drop > baseline_height * FINAL_DROP_RATIO
                if (
                    motion_start_time is None
                    and baseline_height > SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT
                    and len(fighters) == 2
                    and total_ar > TAI_OTOSHI_AR_MIN
                    and height_ratio < 1.05
                ):
                    motion_start_time = t
                upward_spread = (
                    height_ratio > TRIGGER_EXPANSION_RATIO
                    and total_drop < -baseline_height * TRIGGER_UPWARD_TOP_RATIO
                )
                tai_otoshi_rotation = (
                    len(fighters) == 2
                    and baseline_height > SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT
                    and total_ar > TAI_OTOSHI_AR_MIN
                    and height_ratio < TAI_OTOSHI_HEIGHT_RATIO
                    and total_drop > baseline_height * TAI_OTOSHI_DROP_RATIO
                )
                single_occlusion = (
                    len(fighters) == 1
                    and baseline_height > SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT
                    and total_drop > baseline_height * SINGLE_OCCLUSION_DROP_RATIO
                    and height_ratio < SINGLE_OCCLUSION_HEIGHT_RATIO
                )
                attack_shape = len(fighters) == 2 and horizontal_now and (collapsed_now or upward_spread)
                attack_drop = len(fighters) == 2 and lower_now and horizontal_now
                if attack_shape or attack_drop or tai_otoshi_rotation or single_occlusion:
                    attack.start(motion_start_time or t, baseline_top, baseline_height)
                    stats.total_attacks += 1
                    stats.events.append(
                        f"  {t:.1f}s - start akcji "
                        f"(ar {total_ar:.2f}, h_ratio {height_ratio:.2f}, "
                        f"top_drop {total_drop}px)"
                    )
                    alert = "ATAK / RZUT"
                    attack_started = True

            if not attack_started and (
                fighters_standing(fighters)
                and combined.aspect < BASELINE_AR_MAX
                and len(fighters) == 2
            ):
                baseline_top = combined.y1
                baseline_height = combined.height
                alert = "KLINCH / STOJKA"
            elif not attack_started and baseline_top is None:
                baseline_top = combined.y1
                baseline_height = combined.height
                motion_start_time = None
                alert = "KLINCH / BASELINE"

        status = "PARTER" if total_ar > HORIZONTAL_TOTAL_AR else "STOJKA"
        if status == "PARTER":
            stats.newaza_time += dt
        else:
            stats.tachiwaza_time += dt

        for idx, fighter in enumerate(fighters[:2]):
            draw_skeleton(frame, fighter, COLOR_P1 if idx == 0 else COLOR_P2)
        if attack.active:
            draw_combined_box(frame, combined)

        draw_hud(
            frame,
            stats,
            iou,
            total_ar,
            attack.frame_counter if attack.active else 0,
            window_size,
            baseline_height or attack.baseline_height,
            status,
            alert,
        )
        writer.write(frame)

        if combined is not None and recently_touching and not attack.active and frame_i >= attack.cooldown_until:
            was_touching = True
        elif not attack.active and frame_i >= attack.cooldown_until:
            motion_start_time = None
            was_touching = False

        frame_i += 1

    if attack.active:
        final_top = last_combined.y1 if last_combined is not None else -1
        final_ar = last_combined.aspect if last_combined is not None else 0.0
        final_height = last_combined.height if last_combined is not None else 0
        final_top_drop = final_top - attack.baseline_top
        final_success = (
            last_combined is not None
            and (
                final_top_drop > attack.baseline_height * FINAL_SUCCESS_DROP_RATIO
                or attack.max_top_drop > attack.baseline_height * FINAL_SUCCESS_DROP_RATIO
                or (
                    attack.baseline_height > SINGLE_OCCLUSION_MIN_BASELINE_HEIGHT
                    and attack.max_top_drop > attack.baseline_height * FINAL_BIG_BODY_DROP_RATIO
                )
                or (
                    final_ar > HORIZONTAL_TOTAL_AR
                    and final_height < attack.baseline_height * FINAL_HEIGHT_RATIO
                )
                or final_height < attack.baseline_height * FINAL_COMPACT_HEIGHT_RATIO
            )
        )
        if final_success:
            stats.successful_throws += 1
            print(f"{attack.start_time:.1f}s: wykryty atak: udany rzut")
            stats.events.append(
                f"  {attack.start_time:.1f}s: wykryty atak: udany rzut "
                f"(final_top {final_top}px, final_ar {final_ar:.2f}, "
                f"final_h {final_height}px, max_drop {attack.max_top_drop}px, "
                f"max_ar {attack.max_ar:.2f}, min_h {attack.min_height}px, "
                f"baseline_h {attack.baseline_height}px)"
            )
        else:
            stats.failed_throws += 1
            print(f"{attack.start_time:.1f}s: wykryty atak: nieudany atak")
            stats.events.append(
                f"  {attack.start_time:.1f}s: wykryty atak: nieudany atak "
                f"(final_top {final_top}px, final_ar {final_ar:.2f}, "
                f"final_h {final_height}px, max_drop {attack.max_top_drop}px, "
                f"max_ar {attack.max_ar:.2f}, min_h {attack.min_height}px, "
                f"baseline_h {attack.baseline_height}px)"
            )
        attack.finish(frame_i, cooldown_size)

    cap.release()
    writer.release()

    duration = frame_i / fps
    report_path = REPORTS_DIR / f"raport_{video_path.stem}.txt"
    write_report(report_path, video_path, duration, stats)
    print(f"[JudoIQ] Wideo: {out_path}")
    print(f"[JudoIQ] Raport: {report_path}")
    print(
        f"Ataki={stats.total_attacks}, "
        f"Rzuty={stats.successful_throws}, "
        f"Nieudane={stats.failed_throws}"
    )
    return build_analysis_result(video_path, duration, stats, out_path, report_path)


def main() -> int:
    try:
        video = find_video()
    except FileNotFoundError as exc:
        print(f"[BLAD] {exc}", file=sys.stderr)
        return 1
    print(f"[JudoIQ] Analiza: {video.name}")
    analyze(video)
    return 0


if __name__ == "__main__":
    sys.exit(main())