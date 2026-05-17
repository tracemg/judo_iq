#!/usr/bin/env python3
"""JudoIQ – hybrydowy tracking zawodników i detekcja rzutów."""

from __future__ import annotations

import json
import math
import sys
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
VIDEOS_DIR = ROOT / "videos"
REPORTS_DIR = ROOT / "outputs" / "raporty"
VIDEO_OUT_DIR = ROOT / "outputs" / "wideo"
VIDEO_EXT = {".mp4", ".mov", ".avi"}

MAT_Y_MIN_RATIO = 0.30
CONF = 0.45
KEYPOINT_CONF = 0.35

SKELETON = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
)

P1_COLOR = (80, 220, 100)
P2_COLOR = (100, 180, 255)
ALERT_COLOR = (0, 0, 255)
HUD_BG = (0, 0, 0)
HUD_TEXT = (0, 255, 255)

JUDO_BLUE_HSV_LOW = np.array([90, 80, 40], dtype=np.uint8)
JUDO_BLUE_HSV_HIGH = np.array([130, 255, 255], dtype=np.uint8)
JUDO_WHITE_V_MIN = 180
JUDO_WHITE_S_MAX = 60
JUDO_COLOR_RATIO_MIN = 0.30
BLUE_DOMINANCE_RATIO = 0.22

KP_NOSE = 0
KP_L_SHOULDER = 5
KP_R_SHOULDER = 6
KP_L_HIP = 11
KP_R_HIP = 12

SMOOTHING_WINDOW = 5
ATTACK_DISTANCE_DROP = 0.08
SPINE_ATTACK_DEG = 35.0
IMPACT_WINDOW_FRAMES = 30
THROW_LOCKOUT_FRAMES = 45
IMPACT_VELOCITY_Y = 0.030
IMPACT_STOP_VELOCITY_Y = 0.004
IMPACT_STOP_MAX_FRAMES = 2
OVER_UNDER_Y_DELTA = 0.15
NEWAZA_Y_THRESHOLD = 0.68
NEWAZA_HOLD_FRAMES = 15
KALMAN_MAX_MISSED_FRAMES = 20
BBOX_ASPECT_GROWTH_RATIO = 1.50
BBOX_CENTER_DROP_Y = 0.050


class Phase(Enum):
    TACHIWAZA = auto()
    NEWAZA = auto()


@dataclass
class Detection:
    keypoints: np.ndarray
    bbox: tuple[int, int, int, int]
    cog: tuple[float, float]
    cog_norm: tuple[float, float]
    bbox_center_norm: tuple[float, float]
    aspect_ratio: float
    spine_angle: float
    judogi_color: str
    area: float
    keypoints_valid: bool


@dataclass
class PlayerProfile:
    name: str
    display_label: str
    color: tuple[int, int, int]
    color_label: Optional[str] = None
    detection: Optional[Detection] = None
    last_cog_norm: Optional[tuple[float, float]] = None
    cog_y_history: deque[float] = field(default_factory=lambda: deque(maxlen=SMOOTHING_WINDOW))
    prev_smooth_y: Optional[float] = None
    velocity_y: float = 0.0
    predicted_cog_norm: Optional[tuple[float, float]] = None
    missed_frames: int = 0
    prev_aspect_ratio: Optional[float] = None
    aspect_ratio: Optional[float] = None
    aspect_ratio_growth: float = 0.0
    prev_bbox_center_y: Optional[float] = None
    bbox_center_y: Optional[float] = None
    bbox_center_velocity_y: float = 0.0
    kalman: cv2.KalmanFilter = field(init=False)

    def __post_init__(self) -> None:
        self.kalman = cv2.KalmanFilter(4, 2, 0)
        self.kalman.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]],
            dtype=np.float32,
        )
        self.kalman.measurementMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0]],
            dtype=np.float32,
        )
        self.kalman.processNoiseCov = np.eye(4, dtype=np.float32) * 0.002
        self.kalman.measurementNoiseCov = np.eye(2, dtype=np.float32) * 0.025
        self.kalman.errorCovPost = np.eye(4, dtype=np.float32)
        self.kalman.statePost = np.zeros((4, 1), dtype=np.float32)

    def update(self, detection: Detection) -> None:
        if self.last_cog_norm is None:
            self.kalman.statePost = np.array(
                [[detection.cog_norm[0]], [detection.cog_norm[1]], [0.0], [0.0]],
                dtype=np.float32,
            )
        else:
            measurement = np.array(
                [[detection.cog_norm[0]], [detection.cog_norm[1]]],
                dtype=np.float32,
            )
            self.kalman.correct(measurement)

        self.detection = detection
        self.last_cog_norm = detection.cog_norm
        self.predicted_cog_norm = detection.cog_norm
        self.missed_frames = 0
        self.cog_y_history.append(detection.cog_norm[1])
        smooth_y = self.smooth_cog_y
        if self.prev_smooth_y is None:
            self.velocity_y = 0.0
        else:
            self.velocity_y = smooth_y - self.prev_smooth_y
        self.prev_smooth_y = smooth_y
        self._update_bbox_motion(detection)

    def predict(self) -> tuple[float, float]:
        prediction = self.kalman.predict()
        x = float(np.clip(prediction[0, 0], 0.0, 1.0))
        y = float(np.clip(prediction[1, 0], 0.0, 1.0))
        self.predicted_cog_norm = (x, y)
        return self.predicted_cog_norm

    def update_from_prediction(self) -> None:
        if self.predicted_cog_norm is None:
            return
        self.detection = None
        self.last_cog_norm = self.predicted_cog_norm
        self.missed_frames += 1
        self.cog_y_history.append(self.predicted_cog_norm[1])
        smooth_y = self.smooth_cog_y
        if self.prev_smooth_y is None:
            self.velocity_y = 0.0
        else:
            self.velocity_y = smooth_y - self.prev_smooth_y
        self.prev_smooth_y = smooth_y

    def _update_bbox_motion(self, detection: Detection) -> None:
        self.prev_aspect_ratio = self.aspect_ratio
        self.aspect_ratio = detection.aspect_ratio
        if self.prev_aspect_ratio and self.prev_aspect_ratio > 1e-6:
            self.aspect_ratio_growth = self.aspect_ratio / self.prev_aspect_ratio
        else:
            self.aspect_ratio_growth = 1.0

        self.prev_bbox_center_y = self.bbox_center_y
        self.bbox_center_y = detection.bbox_center_norm[1]
        if self.prev_bbox_center_y is None:
            self.bbox_center_velocity_y = 0.0
        else:
            self.bbox_center_velocity_y = self.bbox_center_y - self.prev_bbox_center_y

    @property
    def smooth_cog_y(self) -> float:
        if not self.cog_y_history:
            return self.predicted_cog_norm[1] if self.predicted_cog_norm else 0.0
        return float(sum(self.cog_y_history) / len(self.cog_y_history))

    @property
    def cog_x(self) -> float:
        if self.last_cog_norm is None:
            return self.predicted_cog_norm[0] if self.predicted_cog_norm else 0.0
        return self.last_cog_norm[0]

    @property
    def spine_angle(self) -> float:
        if self.detection is None:
            return 0.0
        return self.detection.spine_angle


@dataclass
class Stats:
    tachiwaza_time: float = 0.0
    newaza_time: float = 0.0
    total_attacks: int = 0
    successful_throws: int = 0
    failed_throws: int = 0
    highlights: list[str] = field(default_factory=list)


def find_video() -> Path:
    files = sorted(p for p in VIDEOS_DIR.iterdir() if p.suffix.lower() in VIDEO_EXT)
    if not files:
        raise FileNotFoundError(f"Brak wideo w {VIDEOS_DIR}")
    return files[0]


def clip_box(box, frame: np.ndarray) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(v) for v in box)
    h, w = frame.shape[:2]
    x1 = max(0, min(x1, w - 1))
    x2 = max(x1 + 1, min(x2, w))
    y1 = max(0, min(y1, h - 1))
    y2 = max(y1 + 1, min(y2, h))
    return x1, y1, x2, y2


def classify_judogi(frame: np.ndarray, box) -> tuple[bool, str]:
    x1, y1, x2, y2 = clip_box(box, frame)
    box_h = y2 - y1
    box_w = x2 - x1
    ty1 = y1 + int(box_h * 0.25)
    ty2 = y1 + int(box_h * 0.70)
    tx1 = x1 + int(box_w * 0.15)
    tx2 = x2 - int(box_w * 0.15)

    if ty2 <= ty1 or tx2 <= tx1:
        return False, "unknown"

    roi = frame[ty1:ty2, tx1:tx2]
    if roi.size == 0:
        return False, "unknown"

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, JUDO_BLUE_HSV_LOW, JUDO_BLUE_HSV_HIGH)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    white_mask = ((v > JUDO_WHITE_V_MIN) & (s < JUDO_WHITE_S_MAX)).astype(np.uint8) * 255

    total = max(roi.shape[0] * roi.shape[1], 1)
    blue_ratio = cv2.countNonZero(blue_mask) / total
    white_ratio = cv2.countNonZero(white_mask) / total

    if blue_ratio + white_ratio < JUDO_COLOR_RATIO_MIN:
        return False, "unknown"
    if blue_ratio >= BLUE_DOMINANCE_RATIO and blue_ratio > white_ratio:
        return True, "blue"
    return True, "white"


def is_wearing_judogi(frame: np.ndarray, box) -> bool:
    ok, _ = classify_judogi(frame, box)
    return ok


def point_ok(kpts: np.ndarray, idx: int) -> bool:
    return kpts.shape[0] > idx and float(kpts[idx, 2]) >= KEYPOINT_CONF


def hip_center(kpts: np.ndarray) -> Optional[tuple[float, float]]:
    pts = []
    for idx in (KP_L_HIP, KP_R_HIP):
        if point_ok(kpts, idx):
            pts.append((float(kpts[idx, 0]), float(kpts[idx, 1])))
    if not pts:
        return None
    arr = np.array(pts)
    return float(arr[:, 0].mean()), float(arr[:, 1].mean())


def spine_angle(kpts: np.ndarray, hip: tuple[float, float]) -> float:
    shoulder_pts = []
    for idx in (KP_L_SHOULDER, KP_R_SHOULDER):
        if point_ok(kpts, idx):
            shoulder_pts.append((float(kpts[idx, 0]), float(kpts[idx, 1])))
    if not shoulder_pts:
        return 0.0
    shoulders = np.array(shoulder_pts)
    neck = np.array([shoulders[:, 0].mean(), shoulders[:, 1].mean()])
    hip_vec = np.array(hip)
    vec = neck - hip_vec
    norm = np.linalg.norm(vec)
    if norm < 1e-6:
        return 0.0
    vertical = np.array([0.0, -1.0])
    cos_angle = float(np.clip(np.dot(vec / norm, vertical), -1.0, 1.0))
    return math.degrees(math.acos(cos_angle))


def extract_detections(frame: np.ndarray, result) -> list[Detection]:
    if result.keypoints is None or result.boxes is None:
        return []
    kpts_all = result.keypoints.data
    boxes = result.boxes.xyxy.cpu().numpy()
    if kpts_all is None or len(boxes) == 0:
        return []

    h, w = frame.shape[:2]
    detections: list[Detection] = []
    for i, box in enumerate(boxes):
        if i >= len(kpts_all):
            break
        ok, color = classify_judogi(frame, box)
        if not ok:
            continue
        x1, y1, x2, y2 = clip_box(box, frame)
        kpts = kpts_all[i].cpu().numpy()
        hip = hip_center(kpts)
        keypoints_valid = hip is not None
        if hip is None:
            hip = ((x1 + x2) / 2.0, y1 + (y2 - y1) * 0.58)
        if hip[1] < h * MAT_Y_MIN_RATIO:
            continue
        area = float(max(x2 - x1, 0) * max(y2 - y1, 0))
        box_w = max(x2 - x1, 1)
        box_h = max(y2 - y1, 1)
        bbox_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        detections.append(
            Detection(
                keypoints=kpts,
                bbox=(x1, y1, x2, y2),
                cog=hip,
                cog_norm=(hip[0] / max(w, 1), hip[1] / max(h, 1)),
                bbox_center_norm=(bbox_center[0] / max(w, 1), bbox_center[1] / max(h, 1)),
                aspect_ratio=box_w / box_h,
                spine_angle=spine_angle(kpts, hip),
                judogi_color=color,
                area=area,
                keypoints_valid=keypoints_valid,
            )
        )
    return detections


class HybridPlayerTracker:
    def __init__(self) -> None:
        self.player1 = PlayerProfile("player1", "P1", P1_COLOR)
        self.player2 = PlayerProfile("player2", "P2", P2_COLOR)
        self.initialized = False

    @property
    def players(self) -> tuple[PlayerProfile, PlayerProfile]:
        return self.player1, self.player2

    def update(self, detections: list[Detection]) -> bool:
        self.player1.predict()
        self.player2.predict()

        if len(detections) < 2 and not self.initialized:
            return False

        if not self.initialized:
            chosen = sorted(detections, key=lambda d: d.area, reverse=True)[:2]
            chosen.sort(key=lambda d: d.cog_norm[0])
            self._lock_colors_if_distinct(chosen[0], chosen[1])
            self.player1.update(chosen[0])
            self.player2.update(chosen[1])
            self.initialized = True
            return True

        if len(detections) == 0:
            self.player1.update_from_prediction()
            self.player2.update_from_prediction()
            return self._has_active_tracks()

        if len(detections) == 1:
            det = detections[0]
            p1_cost = self._assignment_cost(self.player1, det)
            p2_cost = self._assignment_cost(self.player2, det)
            if p1_cost <= p2_cost:
                self.player1.update(det)
                self.player2.update_from_prediction()
            else:
                self.player2.update(det)
                self.player1.update_from_prediction()
            return self._has_active_tracks()

        best_pair: Optional[tuple[float, Detection, Detection]] = None
        pool = sorted(detections, key=lambda d: d.area, reverse=True)[:6]
        for i, d1 in enumerate(pool):
            for j, d2 in enumerate(pool):
                if i == j:
                    continue
                score = self._assignment_cost(self.player1, d1) + self._assignment_cost(self.player2, d2)
                if best_pair is None or score < best_pair[0]:
                    best_pair = (score, d1, d2)

        if best_pair is None:
            return False

        _, d1, d2 = best_pair
        self._lock_colors_if_distinct(d1, d2)
        self.player1.update(d1)
        self.player2.update(d2)
        return True

    def _assignment_cost(self, player: PlayerProfile, det: Detection) -> float:
        reference = player.predicted_cog_norm or player.last_cog_norm
        if reference is None:
            base = 0.0
        else:
            dx = det.cog_norm[0] - reference[0]
            dy = det.cog_norm[1] - reference[1]
            base = math.hypot(dx, dy)
        if player.color_label and det.judogi_color != player.color_label:
            base += 0.35
        return base

    def _lock_colors_if_distinct(self, d1: Detection, d2: Detection) -> None:
        colors = {d1.judogi_color, d2.judogi_color}
        if colors == {"blue", "white"}:
            self.player1.color_label = d1.judogi_color
            self.player2.color_label = d2.judogi_color

    def _has_active_tracks(self) -> bool:
        return (
            self.initialized
            and self.player1.last_cog_norm is not None
            and self.player2.last_cog_norm is not None
            and self.player1.missed_frames <= KALMAN_MAX_MISSED_FRAMES
            and self.player2.missed_frames <= KALMAN_MAX_MISSED_FRAMES
        )


@dataclass
class AttackState:
    open: bool = False
    start_frame: int = 0
    impact_player: Optional[str] = None
    impact_frame: Optional[int] = None
    lockout_until: int = -1
    baseline_aspect: dict[str, float] = field(default_factory=dict)
    baseline_center_y: dict[str, float] = field(default_factory=dict)

    def start(self, frame_i: int, players: tuple[PlayerProfile, PlayerProfile]) -> None:
        self.open = True
        self.start_frame = frame_i
        self.impact_player = None
        self.impact_frame = None
        self.baseline_aspect = {}
        self.baseline_center_y = {}
        for player in players:
            if player.aspect_ratio is not None:
                self.baseline_aspect[player.name] = player.aspect_ratio
            if player.bbox_center_y is not None:
                self.baseline_center_y[player.name] = player.bbox_center_y

    def close_with_lockout(self, frame_i: int) -> None:
        self.open = False
        self.impact_player = None
        self.impact_frame = None
        self.baseline_aspect.clear()
        self.baseline_center_y.clear()
        self.lockout_until = frame_i + THROW_LOCKOUT_FRAMES


def horizontal_distance(p1: PlayerProfile, p2: PlayerProfile) -> float:
    return abs(p1.cog_x - p2.cog_x)


def build_ws_payload(
    p1: PlayerProfile,
    p2: PlayerProfile,
    is_kuzushi: bool,
    new_highlight: str,
    stats: Stats,
) -> dict:
    return {
        "p1_cog_y": float(p1.smooth_cog_y),
        "p2_cog_y": float(p2.smooth_cog_y),
        "is_kuzushi": bool(is_kuzushi),
        "new_highlight": new_highlight,
        "tachiwaza_time": int(stats.tachiwaza_time),
        "newaza_time": int(stats.newaza_time),
        "total_attacks": int(stats.total_attacks),
        "successful_throws": int(stats.successful_throws),
        "failed_throws": int(stats.failed_throws),
    }


def bbox_throw_signal(player: PlayerProfile, attack: AttackState) -> bool:
    if player.aspect_ratio is None or player.bbox_center_y is None:
        return False
    baseline_ar = attack.baseline_aspect.get(player.name)
    baseline_y = attack.baseline_center_y.get(player.name)
    if baseline_ar is None or baseline_y is None or baseline_ar <= 1e-6:
        return False
    aspect_ok = player.aspect_ratio >= baseline_ar * BBOX_ASPECT_GROWTH_RATIO
    drop_ok = (player.bbox_center_y - baseline_y) >= BBOX_CENTER_DROP_Y
    velocity_ok = player.bbox_center_velocity_y >= BBOX_CENTER_DROP_Y / 2.0
    return aspect_ok and (drop_ok or velocity_ok)


def draw_skeleton(frame: np.ndarray, player: PlayerProfile) -> None:
    det = player.detection
    if det is None:
        if player.predicted_cog_norm is not None:
            h, w = frame.shape[:2]
            cx = int(player.predicted_cog_norm[0] * w)
            cy = int(player.predicted_cog_norm[1] * h)
            cv2.circle(frame, (cx, cy), 12, player.color, 2, cv2.LINE_AA)
            cv2.putText(
                frame,
                f"{player.display_label} (kalman)",
                (max(cx - 50, 0), max(cy - 16, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                player.color,
                2,
                cv2.LINE_AA,
            )
        return
    k = det.keypoints
    for i, j in SKELETON:
        if not point_ok(k, i) or not point_ok(k, j):
            continue
        cv2.line(
            frame,
            (int(k[i, 0]), int(k[i, 1])),
            (int(k[j, 0]), int(k[j, 1])),
            player.color,
            2,
            cv2.LINE_AA,
        )
    x1, y1, x2, y2 = det.bbox
    label = f"{player.display_label} ({det.judogi_color})"
    cv2.rectangle(frame, (x1, y1), (x2, y2), player.color, 2)
    cv2.putText(
        frame,
        label,
        (x1, max(y1 - 8, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        player.color,
        2,
        cv2.LINE_AA,
    )


def draw_hud(frame: np.ndarray, payload: dict, dist_x: float) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (520, 178), HUD_BG, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    lines = [
        f"P1 CoG Y: {payload['p1_cog_y']:.3f}",
        f"P2 CoG Y: {payload['p2_cog_y']:.3f}",
        f"Dystans X: {dist_x:.3f}",
        f"Kuzushi: {payload['is_kuzushi']}",
        f"Ataki: {payload['total_attacks']} | Rzuty: {payload['successful_throws']} | Fail: {payload['failed_throws']}",
    ]
    for idx, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (16, 36 + idx * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            HUD_TEXT,
            2,
            cv2.LINE_AA,
        )


def draw_attack_alert(frame: np.ndarray, text: str) -> None:
    if not text:
        return
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - 72), (w, h), ALERT_COLOR, -1)
    cv2.putText(
        frame,
        text,
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
        f"- Łączna liczba prób ataków: {stats.total_attacks}",
        f"- Udane rzuty / obalenia: {stats.successful_throws}",
        f"- Nieudane akcje: {stats.failed_throws}",
        "-----------------------------------------",
        "HIGHLIGHTY:",
    ]
    lines.extend(stats.highlights or ["  (brak)"])
    lines.extend(["=========================================", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def analyze(video_path: Path) -> None:
    model = YOLO("yolov8n-pose.pt")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Nie mozna otworzyc: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dt = 1.0 / fps

    out_path = VIDEO_OUT_DIR / f"anotowany_{video_path.stem}.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)
    )

    tracker = HybridPlayerTracker()
    stats = Stats()
    attack = AttackState()
    distance_history: deque[float] = deque(maxlen=SMOOTHING_WINDOW)
    newaza_hold = 0
    phase = Phase.TACHIWAZA
    last_payload: dict = {}

    frame_i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t = frame_i / fps
        result = model(frame, verbose=False, conf=CONF)[0]
        detections = extract_detections(frame, result)
        has_players = tracker.update(detections)

        is_kuzushi = False
        new_highlight = ""
        dist_x = 0.0

        if has_players:
            p1, p2 = tracker.players
            dist_x = horizontal_distance(p1, p2)
            old_dist = distance_history[0] if len(distance_history) == SMOOTHING_WINDOW else dist_x
            distance_history.append(dist_x)
            distance_drop = old_dist - dist_x
            spine_trigger = max(p1.spine_angle, p2.spine_angle) >= SPINE_ATTACK_DEG
            is_kuzushi = distance_drop > ATTACK_DISTANCE_DROP and spine_trigger

            if p1.smooth_cog_y >= NEWAZA_Y_THRESHOLD or p2.smooth_cog_y >= NEWAZA_Y_THRESHOLD:
                newaza_hold += 1
            else:
                newaza_hold = 0
            phase = Phase.NEWAZA if newaza_hold >= NEWAZA_HOLD_FRAMES else Phase.TACHIWAZA

            if is_kuzushi and not attack.open and frame_i >= attack.lockout_until:
                attack.start(frame_i, (p1, p2))
                stats.total_attacks += 1
                new_highlight = "ATAK"
                stats.highlights.append(f"{t:.1f}s - atak")

            if attack.open:
                for player in (p1, p2):
                    if player.velocity_y >= IMPACT_VELOCITY_Y:
                        attack.impact_player = player.name
                        attack.impact_frame = frame_i

                if attack.impact_player and attack.impact_frame is not None:
                    p_fall = p1 if attack.impact_player == "player1" else p2
                    p_other = p2 if attack.impact_player == "player1" else p1
                    age = frame_i - attack.impact_frame
                    stopped = p_fall.velocity_y <= IMPACT_STOP_VELOCITY_Y
                    over_under = (p_fall.smooth_cog_y - p_other.smooth_cog_y) >= OVER_UNDER_Y_DELTA
                    if age <= IMPACT_STOP_MAX_FRAMES and stopped and over_under:
                        stats.successful_throws += 1
                        attack.close_with_lockout(frame_i)
                        new_highlight = "UDANY RZUT"
                        stats.highlights.append(f"{t:.1f}s - udany rzut")

                if attack.open:
                    for player in (p1, p2):
                        keypoints_missing = (
                            player.detection is None
                            or not player.detection.keypoints_valid
                            or player.missed_frames > 0
                        )
                        if keypoints_missing and bbox_throw_signal(player, attack):
                            stats.successful_throws += 1
                            attack.close_with_lockout(frame_i)
                            new_highlight = "UDANY RZUT (BBOX)"
                            stats.highlights.append(f"{t:.1f}s - udany rzut bbox")
                            break

                if attack.open and frame_i - attack.start_frame > IMPACT_WINDOW_FRAMES:
                    stats.failed_throws += 1
                    attack.close_with_lockout(frame_i)
                    new_highlight = "NIEUDANY ATAK"
                    stats.highlights.append(f"{t:.1f}s - nieudany atak")

            if phase == Phase.TACHIWAZA:
                stats.tachiwaza_time += dt
            else:
                stats.newaza_time += dt

            for player in (p1, p2):
                draw_skeleton(frame, player)

            last_payload = build_ws_payload(p1, p2, is_kuzushi, new_highlight, stats)
            draw_hud(frame, last_payload, dist_x)
            if attack.open or new_highlight:
                draw_attack_alert(frame, new_highlight or "ATAK / IMPAKT")
        else:
            blank = {
                "p1_cog_y": 0.0,
                "p2_cog_y": 0.0,
                "is_kuzushi": False,
                "new_highlight": "",
                "tachiwaza_time": int(stats.tachiwaza_time),
                "newaza_time": int(stats.newaza_time),
                "total_attacks": stats.total_attacks,
                "successful_throws": stats.successful_throws,
                "failed_throws": stats.failed_throws,
            }
            last_payload = blank
            draw_hud(frame, blank, 0.0)

        writer.write(frame)
        frame_i += 1

    cap.release()
    writer.release()

    duration = frame_i / fps
    report_path = REPORTS_DIR / f"raport_{video_path.stem}.txt"
    write_report(report_path, video_path, duration, stats)

    print(f"[JudoIQ] Wideo: {out_path}")
    print(f"[JudoIQ] Raport: {report_path}")
    print(json.dumps(last_payload, ensure_ascii=False))


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
