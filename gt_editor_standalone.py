"""
================================================================================
  ABC2027 TrackID3x3 — Portable Ground-Truth Box & Trajectory Editor (v4)
  100% Standalone Package (Zero hardcoded paths — runs on any Windows/Mac/Linux)
================================================================================
- Automatically reads ./videos_source/IMG_0114.MP4 & IMG_0115.MP4
- Automatically loads & saves ./output_ground_truth/IMG_0114.txt, IMG_0115.txt
  and ./output_ground_truth/IMG_0114_gt_boxes.csv.gz, IMG_0115_gt_boxes.csv.gz
- Automatically computes bottom midpoint u_foot = (x1 + x2)/2, v_foot = y2
  and projects via Official BTC 4-Point Homography (RKU0, RKU1, RKU10, RKU11)
  to (court_x, court_y) in cm.
- Automatically picks a free port (starting at 8899) so it never collides with
  any other local web app.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

PKG_ROOT = Path(__file__).resolve().parent
VIDEOS_DIR = PKG_ROOT / "videos_source"
GT_DIR = PKG_ROOT / "output_ground_truth"
GT_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def extract_gdrive_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    m = re.search(r"/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]{20,})", s)
    if m:
        return m.group(1)
    m2 = re.search(r"id=([a-zA-Z0-9_-]{20,})", s)
    if m2:
        return m2.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{25,}$", s):
        return s
    return s


def download_from_gdrive(url_or_id: str, dest_path: Path) -> int:
    file_id = extract_gdrive_id(url_or_id)
    tmp_path = dest_path.with_suffix(".tmp_download")
    if tmp_path.exists():
        tmp_path.unlink()

    # If it is a direct non-Google Drive URL
    if url_or_id.startswith("http") and ("drive.google.com" not in url_or_id and "docs.google.com" not in url_or_id):
        req = urllib.request.Request(url_or_id, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as out_f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
    else:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        download_url = f"https://docs.google.com/uc?export=download&id={file_id}"
        req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = opener.open(req)

        content_type = resp.headers.get("Content-Type", "")
        # Check if Google Drive returned a virus scan warning confirmation page
        if "text/html" in content_type:
            html = resp.read().decode("utf-8", errors="ignore")
            confirm_m = re.search(r"confirm=([0-9A-Za-z_-]+)", html)
            if confirm_m:
                download_url = f"https://docs.google.com/uc?export=download&confirm={confirm_m.group(1)}&id={file_id}"
            else:
                form_m = re.search(r'action="([^"]+)"', html)
                if form_m:
                    download_url = form_m.group(1).replace("&amp;", "&")
                else:
                    href_m = re.search(r'href="(https://drive\.usercontent\.google\.com/download[^"]+)"', html)
                    if href_m:
                        download_url = href_m.group(1).replace("&amp;", "&")
            req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
            resp = opener.open(req)

        with open(tmp_path, "wb") as out_f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)

    if not tmp_path.exists() or tmp_path.stat().st_size < 1000:
        if tmp_path.exists():
            tmp_path.unlink()
        raise ValueError("Download failed or file is too small. Please ensure the Google Drive file is set to 'Anyone with the link can view'.")

    if dest_path.exists():
        dest_path.unlink()
    tmp_path.replace(dest_path)
    return dest_path.stat().st_size


# Official BTC 4-Point Court Registration on 720p (1280x720):
#   RKU0 : (1113, 379) -> (0, 0)
#   RKU1 : (955, 531)  -> (0, 1105)
#   RKU10: (512, 305)  -> (1505, 0)
#   RKU11: (141, 374)  -> (1505, 1105)
_IMG_PTS = np.array([[1113.0, 379.0], [955.0, 531.0], [512.0, 305.0], [141.0, 374.0]], dtype=np.float64)
_CRT_PTS = np.array([[0.0, 0.0], [0.0, 1105.0], [1505.0, 0.0], [1505.0, 1105.0]], dtype=np.float64)
H_IMG2COURT, _ = cv2.findHomography(_IMG_PTS, _CRT_PTS, 0)
H_COURT2IMG = np.linalg.inv(H_IMG2COURT)

VIDEOS_720P = {
    "IMG_0114": VIDEOS_DIR / "IMG_0114.MP4",
    "IMG_0115": VIDEOS_DIR / "IMG_0115.MP4",
}
ROSTERS = {
    "IMG_0114": ["A#6", "A#9", "A#10", "B#6", "B#9", "B#11"],
    "IMG_0115": ["A#4", "A#10", "A#12", "B#1", "B#3", "B#5"],
}


def img_to_court(u: float, v: float) -> tuple[float, float]:
    p = H_IMG2COURT @ np.array([u, v, 1.0], dtype=np.float64)
    return round(float(p[0] / p[2]), 2), round(float(p[1] / p[2]), 2)


class VideoStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.caps: dict[str, cv2.VideoCapture] = {}
        self.last_pos: dict[str, int] = {}
        self.data: dict[str, dict] = {}
        self.flagged_frames: dict[str, list[int]] = {}
        self._load_all_gt()

    def _load_all_gt(self):
        for vid in ["IMG_0114", "IMG_0115"]:
            csv_p = GT_DIR / f"{vid}_gt_boxes.csv.gz"
            if not csv_p.exists():
                raise FileNotFoundError(f"Missing {csv_p}! Please keep the output_ground_truth folder intact.")
            df = pd.read_csv(csv_p)
            df["ident"] = df["team"].astype(str) + "#" + df["jersey"].astype(str)
            uniq_r = (
                df[["team", "jersey"]]
                .drop_duplicates()
                .assign(jersey=lambda x: x["jersey"].astype(int))
                .sort_values(["team", "jersey"])
            )
            vid_roster = [f"{r.team}#{int(r.jersey)}" for r in uniq_r.itertuples(index=False)]
            max_f = int(df["frame"].max())
            frames_dict = {}
            flagged = set()
            for r in df.itertuples(index=False):
                f = int(r.frame)
                d = frames_dict.get(f)
                if d is None:
                    d = {}
                    frames_dict[f] = d
                obs = bool(r.observed)
                ed = bool(r.edited) if hasattr(r, "edited") else False
                if not obs:
                    flagged.add(f)
                d[str(r.ident)] = [
                    round(float(r.x1), 2),
                    round(float(r.y1), 2),
                    round(float(r.x2), 2),
                    round(float(r.y2), 2),
                    round(float(r.court_x), 2),
                    round(float(r.court_y), 2),
                    obs,
                    ed,
                ]
            sorted_fl = sorted(flagged)
            bookmarks = []
            prev_f = -999
            for f in sorted_fl:
                if f - prev_f > 8:
                    bookmarks.append(f)
                prev_f = f
            self.data[vid] = {"max_frames": max_f, "roster": vid_roster, "frames": frames_dict}
            self.flagged_frames[vid] = bookmarks
            print(f"[GT Editor v4] Loaded {vid}: {max_f} frames, roster={vid_roster}, {len(bookmarks)} occlusion bookmarks.", flush=True)

    def get_jpeg_frame(self, vid: str, frame_idx: int) -> bytes:
        with self.lock:
            cap = self.caps.get(vid)
            if cap is None:
                cap = cv2.VideoCapture(str(VIDEOS_720P[vid]))
                self.caps[vid] = cap
                self.last_pos[vid] = 0
            target_0 = max(0, frame_idx - 1)
            if self.last_pos.get(vid, -999) != target_0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_0)
            ok, frame = cap.read()
            self.last_pos[vid] = target_0 + 1
            if not ok or frame is None:
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            _, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            return buf.tobytes()

    def update_box(self, vid: str, frame_idx: int, ident: str, x1: float, y1: float, x2: float, y2: float):
        if x2 < x1 + 4:
            x2 = x1 + 4
        if y2 < y1 + 8:
            y2 = y1 + 8
        u_foot = 0.5 * (x1 + x2)
        v_foot = y2
        cx, cy = img_to_court(u_foot, v_foot)
        rec = self.data[vid]["frames"][frame_idx][ident]
        rec[0], rec[1], rec[2], rec[3] = round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)
        rec[4], rec[5] = cx, cy
        rec[7] = True
        return rec

    def interpolate_range(self, vid: str, ident: str, f1: int, f2: int):
        if f1 > f2:
            f1, f2 = f2, f1
        frames = self.data[vid]["frames"]
        b1 = frames[f1][ident][:4]
        b2 = frames[f2][ident][:4]
        span = max(1, f2 - f1)
        for f in range(f1, f2 + 1):
            alpha = (f - f1) / span
            x1 = (1.0 - alpha) * b1[0] + alpha * b2[0]
            y1 = (1.0 - alpha) * b1[1] + alpha * b2[1]
            x2 = (1.0 - alpha) * b1[2] + alpha * b2[2]
            y2 = (1.0 - alpha) * b1[3] + alpha * b2[3]
            self.update_box(vid, f, ident, x1, y1, x2, y2)

    def interpolate_from_anchor(self, vid: str, ident: str, f1: int, f2: int, anchor: int):
        """Interpolate bbox using anchor frame as a fixed keyframe.
        Segment [f1..anchor] is interpolated from bbox@f1 → bbox@anchor,
        and segment [anchor..f2] from bbox@anchor → bbox@f2."""
        if f1 > f2:
            f1, f2 = f2, f1
        anchor = max(f1, min(f2, anchor))
        frames = self.data[vid]["frames"]
        b_anchor = frames[anchor][ident][:4]
        # Left segment: f1 -> anchor
        if anchor > f1:
            b1 = frames[f1][ident][:4]
            span = max(1, anchor - f1)
            for f in range(f1, anchor + 1):
                alpha = (f - f1) / span
                x1 = (1.0 - alpha) * b1[0] + alpha * b_anchor[0]
                y1 = (1.0 - alpha) * b1[1] + alpha * b_anchor[1]
                x2 = (1.0 - alpha) * b1[2] + alpha * b_anchor[2]
                y2 = (1.0 - alpha) * b1[3] + alpha * b_anchor[3]
                self.update_box(vid, f, ident, x1, y1, x2, y2)
        # Right segment: anchor -> f2
        if f2 > anchor:
            b2 = frames[f2][ident][:4]
            span = max(1, f2 - anchor)
            for f in range(anchor, f2 + 1):
                alpha = (f - anchor) / span
                x1 = (1.0 - alpha) * b_anchor[0] + alpha * b2[0]
                y1 = (1.0 - alpha) * b_anchor[1] + alpha * b2[1]
                x2 = (1.0 - alpha) * b_anchor[2] + alpha * b2[2]
                y2 = (1.0 - alpha) * b_anchor[3] + alpha * b2[3]
                self.update_box(vid, f, ident, x1, y1, x2, y2)

    def swap_players_range(self, vid: str, id1: str, id2: str, f1: int, f2: int):
        if f1 > f2:
            f1, f2 = f2, f1
        frames = self.data[vid]["frames"]
        for f in range(f1, f2 + 1):
            r1 = list(frames[f][id1])
            r2 = list(frames[f][id2])
            r1[7] = True
            r2[7] = True
            frames[f][id1] = r2
            frames[f][id2] = r1

    def save_video_gt(self, vid: str) -> dict:
        frames = self.data[vid]["frames"]
        roster = self.data[vid]["roster"]
        max_f = self.data[vid]["max_frames"]
        rows = []
        n_edited = 0
        for f in range(1, max_f + 1):
            fd = frames[f]
            for ident in roster:
                team, jer = ident.split("#")
                r = fd[ident]
                if r[7]:
                    n_edited += 1
                rows.append((f, team, int(jer), r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
        df = pd.DataFrame(
            rows,
            columns=["frame", "team", "jersey", "x1", "y1", "x2", "y2", "court_x", "court_y", "observed", "edited"],
        ).sort_values(["frame", "team", "jersey"]).reset_index(drop=True)
        csv_p = GT_DIR / f"{vid}_gt_boxes.csv.gz"
        txt_p = GT_DIR / f"{vid}.txt"
        df.to_csv(csv_p, index=False)
        df[["frame", "court_x", "court_y", "team", "jersey"]].to_csv(txt_p, index=False, header=False, float_format="%.2f")
        return {"saved_csv": str(csv_p), "saved_txt": str(txt_p), "edited_boxes": n_edited}

    def replace_video_source(self, vid: str, url_or_id: str) -> dict:
        dest_p = VIDEOS_720P.get(vid, VIDEOS_DIR / f"{vid}.MP4")
        with self.lock:
            if vid in self.caps and self.caps[vid] is not None:
                try:
                    self.caps[vid].release()
                except Exception:
                    pass
                del self.caps[vid]
            self.last_pos.pop(vid, None)

        bytes_dl = download_from_gdrive(url_or_id, dest_p)
        mb = round(bytes_dl / (1024 * 1024), 2)

        with self.lock:
            cap = cv2.VideoCapture(str(dest_p))
            if not cap.isOpened():
                raise ValueError("Downloaded file is not a valid video.")
            self.caps[vid] = cap
            self.last_pos[vid] = 0
            fps = cap.get(cv2.CAP_PROP_FPS)
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        return {
            "ok": True,
            "message": f"Đã tải thành công và thay thế {vid}.MP4 ({mb} MB, {count} frames @ {round(fps, 1)} fps)!",
            "size_mb": mb,
            "frames": count,
        }


STORE: VideoStore | None = None

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"/>
<title>3x3 Basketball Ground-Truth Box & Trajectory Editor (Solver v4)</title>
<style>
  * { box-sizing: border-box; user-select: none; }
  body { margin: 0; font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  header { background: #1e293b; padding: 8px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #334155; flex-wrap: wrap; }
  header h1 { font-size: 15px; margin: 0; color: #38bdf8; font-weight: 700; }
  select, input, button { background: #0f172a; color: #f8fafc; border: 1px solid #475569; border-radius: 6px; padding: 5px 10px; font-size: 13px; cursor: pointer; }
  button:hover { background: #334155; }
  button.primary { background: #0284c7; border-color: #38bdf8; font-weight: 600; }
  button.primary:hover { background: #0369a1; }
  button.success { background: #059669; border-color: #34d399; font-weight: 600; }
  button.warn { background: #d97706; border-color: #fbbf24; font-weight: 600; }
  .main { display: flex; flex: 1; overflow: hidden; }
  .canvas-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #020617; position: relative; overflow: hidden; }
  canvas#videoCanvas { max-width: 100%; max-height: calc(100vh - 115px); border: 1px solid #334155; cursor: crosshair; }
  .sidebar { width: 340px; background: #1e293b; border-left: 1px solid #334155; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
  .card { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px; }
  .card h3 { margin: 0 0 8px 0; font-size: 13px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
  .player-list { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .p-btn { padding: 7px 8px; border-radius: 6px; border: 2px solid transparent; font-weight: 700; font-size: 12.5px; text-align: left; display: flex; justify-content: space-between; }
  .p-btn.active { border-color: #ffffff; box-shadow: 0 0 8px rgba(255,255,255,0.4); }
  .footer { background: #1e293b; padding: 8px 16px; border-top: 1px solid #334155; display: flex; align-items: center; gap: 10px; }
  #scrubber { flex: 1; accent-color: #38bdf8; cursor: pointer; }
  .status { font-size: 12px; color: #34d399; font-weight: 600; }
  .kbd { background: #334155; padding: 1px 5px; border-radius: 4px; font-size: 11px; font-family: monospace; }
</style>
</head>
<body>
<header>
  <h1>🏀 3x3 GT Box & Foot Midpoint Editor (v4)</h1>
  <label>Video:
    <select id="vidSelect" onchange="changeVideo()">
      <option value="IMG_0114">IMG_0114 (11,536 frames)</option>
      <option value="IMG_0115">IMG_0115 (11,823 frames)</option>
    </select>
  </label>
  <button onclick="stepFrame(-100)">-100</button>
  <button onclick="stepFrame(-10)">-10 (Q)</button>
  <button onclick="stepFrame(-1)">-1 (A/←)</button>
  <button id="playBtn" class="primary" onclick="togglePlay()">▶ Play (Space)</button>
  <button onclick="stepFrame(1)">+1 (D/→)</button>
  <button onclick="stepFrame(10)">+10 (E)</button>
  <button onclick="stepFrame(100)">+100</button>
  <label>Tốc độ:
    <select id="speedSelect">
      <option value="66">0.5x</option>
      <option value="33" selected>1.0x</option>
      <option value="16">2.0x</option>
    </select>
  </label>
  <button class="warn" onclick="jumpBookmark(-1)">⏮ Prev Occlusion (P)</button>
  <button class="warn" onclick="jumpBookmark(1)">⏭ Next Occlusion (N)</button>
  <button class="primary" onclick="openGdriveModal()" style="background: linear-gradient(135deg, #0284c7, #2563eb); border-color: #38bdf8;">📥 Nạp Video (Drive)</button>
  <button class="success" onclick="saveGT()">💾 Lưu GT (Ctrl+S)</button>
  <button class="primary" onclick="downloadGT()">⬇️ Tải File Chuẩn (.txt)</button>
  <span id="saveStatus" class="status">Sẵn sàng</span>
</header>

<div class="main">
  <div class="canvas-wrap">
    <canvas id="videoCanvas" width="1280" height="720"></canvas>
  </div>
  <div class="sidebar">
    <div class="card">
      <h3>1. Chọn Cầu Thủ (Phím 1..6)</h3>
      <div id="playerBtns" class="player-list"></div>
      <div style="margin-top:8px; display:flex; gap:6px;">
        <button id="drawModeBtn" style="flex:1" onclick="toggleDrawMode()">✏️ Chế độ Vẽ Lại Box (W): OFF</button>
        <button style="flex:1" onclick="copyPrevFrame()">📋 Copy Frame Trước (C)</button>
      </div>
    </div>

    <div class="card">
      <h3>2. Thông Số Box & Trung Điểm Đáy</h3>
      <div id="boxInfo" style="font-size:12.5px; line-height:1.6; font-family:monospace;"></div>
      <div style="font-size:11.5px; color:#94a3b8; margin-top:4px;">
        * Điểm chân luôn tự động lấy <b>trung điểm cạnh đáy</b> <code>((x1+x2)/2, y2)</code> và quy đổi sang tọa độ sân chuẩn BTC.
      </div>
    </div>

    <div class="card">
      <h3>3. Nội Suy & Đổi Nhãn Theo Đoạn Frame</h3>
      <div style="display:flex; gap:6px; align-items:center; margin-bottom:8px;">
        <button onclick="setRangeStart()">Đặt Đầu [I]</button>
        <input id="fStart" type="number" value="1" style="width:72px"/>
        <span>→</span>
        <input id="fEnd" type="number" value="10" style="width:72px"/>
        <button onclick="setRangeEnd()">Đặt Cuối [O]</button>
      </div>
      <button class="primary" style="width:100%; margin-bottom:8px;" onclick="interpolateRange()">
        ✨ Nội Suy Box Cầu Thủ Đang Chọn [f_đầu..f_cuối] (K)
      </button>
      <button class="primary" style="width:100%; margin-bottom:8px; background: linear-gradient(135deg,#7c3aed,#2563eb);" onclick="interpolateFromAnchor()">
        🔑 Nội Suy Từ Box Frame Hiện Tại Làm Anchor [f_đầu..f_hiện..f_cuối] (J)
      </button>
      <div style="display:flex; gap:6px; align-items:center;">
        <select id="swapA" style="flex:1"></select>
        <span>⇄</span>
        <select id="swapB" style="flex:1"></select>
        <button class="warn" onclick="swapRange()">Swap ID</button>
      </div>
    </div>

    <div class="card">
      <h3>Phím Tắt Nhanh</h3>
      <div style="font-size:12px; line-height:1.7; color:#cbd5e1;">
        <div><span class="kbd">Kéo giữa Box</span>: Di chuyển cả Box</div>
        <div><span class="kbd">Kéo 8 chốt cạnh/góc</span>: Co giãn Box</div>
        <div><span class="kbd">W</span>: Bật/tắt quét chuột vẽ Box mới</div>
        <div><span class="kbd">C</span>: Copy Box từ frame trước & tiến +1 frame</div>
        <div><span class="kbd">I</span> / <span class="kbd">O</span> / <span class="kbd">K</span>: Đặt f_đầu / f_cuối / Nội suy đoạn</div>
        <div><span class="kbd">J</span>: Nội suy từ box frame hiện tại làm anchor</div>
        <div><span class="kbd">N</span> / <span class="kbd">P</span>: Nhảy tới frame nội suy/che khuất</div>
        <div><span class="kbd">Ctrl+S</span>: Lưu Ground Truth vào <code>output_ground_truth/</code></div>
      </div>
    </div>
  </div>
</div>

<div class="footer">
  <span>Frame:</span>
  <input id="frameInput" type="number" value="1" min="1" max="11823" style="width:82px; font-weight:700;" onchange="goToFrame(parseInt(this.value))"/>
  <span id="maxFrameLbl">/ 11823</span>
  <input id="scrubber" type="range" min="1" max="11823" value="1" oninput="goToFrame(parseInt(this.value))"/>
</div>

<script>
let curVid = "IMG_0114";
let curFrame = 1;
let maxFrames = 11823;
let roster = [];
let frameData = {};
let bookmarks = [];
let selectedIdent = "A#4";
let playing = false;
let playTimer = null;
let drawNewBoxMode = false;

const canvas = document.getElementById("videoCanvas");
const ctx = canvas.getContext("2d");
let bgImg = new Image();
let dragState = null;

// 1 unified color per team (Team A: Gold, Team B: Cyan)
const TEAM_COLORS = {
  "A": "#ffd700",
  "B": "#00c3ff"
};

async function initVideoMeta() {
  const res = await fetch(`/api/meta?video=${curVid}`);
  const meta = await res.json();
  maxFrames = meta.max_frames;
  roster = meta.roster;
  bookmarks = meta.bookmarks;
  selectedIdent = roster[0];
  document.getElementById("scrubber").max = maxFrames;
  document.getElementById("frameInput").max = maxFrames;
  document.getElementById("maxFrameLbl").textContent = `/ ${maxFrames}`;

  const pWrap = document.getElementById("playerBtns");
  const swA = document.getElementById("swapA");
  const swB = document.getElementById("swapB");
  pWrap.innerHTML = "";
  swA.innerHTML = "";
  swB.innerHTML = "";
  roster.forEach((id, idx) => {
    const team = id.split("#")[0];
    const btn = document.createElement("button");
    btn.className = "p-btn" + (id === selectedIdent ? " active" : "");
    btn.style.background = team === "A" ? "#422006" : "#083344";
    btn.style.color = TEAM_COLORS[team];
    btn.innerHTML = `<span>[${idx+1}] ${id}</span><span id="tag_${id}"></span>`;
    btn.onclick = () => selectPlayer(id);
    btn.id = `pbtn_${id}`;
    pWrap.appendChild(btn);

    swA.add(new Option(id, id));
    swB.add(new Option(id, id));
  });
  if (roster.length > 1) swB.selectedIndex = 1;
  await goToFrame(1);
}

function selectPlayer(id) {
  selectedIdent = id;
  roster.forEach(r => {
    const el = document.getElementById(`pbtn_${r}`);
    if (el) el.className = "p-btn" + (r === id ? " active" : "");
  });
  renderCanvas();
  updateSidebarInfo();
}

async function changeVideo() {
  if (playing) togglePlay();
  curVid = document.getElementById("vidSelect").value;
  await initVideoMeta();
}

let targetFrame = 1;
let fetchInFlight = false;

function loadBgImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(bgImg);
    img.src = url;
  });
}

const H_I2C = [
  [-2.20389151, -1.78791761, 3132.55939],
  [ 0.14568352,  9.29818661, -3686.26259],
  [-0.00010539,  0.00438661,     1.0    ]
];
function clientImgToCourt(u, v) {
  const w = H_I2C[2][0] * u + H_I2C[2][1] * v + H_I2C[2][2];
  const cx = (H_I2C[0][0] * u + H_I2C[0][1] * v + H_I2C[0][2]) / w;
  const cy = (H_I2C[1][0] * u + H_I2C[1][1] * v + H_I2C[1][2]) / w;
  return [cx, cy];
}

async function goToFrame(f) {
  f = Math.max(1, Math.min(maxFrames, f));
  curFrame = f;
  targetFrame = f;
  document.getElementById("frameInput").value = f;
  document.getElementById("scrubber").value = f;
  if (fetchInFlight) return;
  fetchInFlight = true;
  try {
    while (true) {
      const fetchF = targetFrame;
      const [data, img] = await Promise.all([
        fetch(`/api/frame_data?video=${curVid}&frame=${fetchF}`).then(r => r.json()),
        loadBgImage(`/api/frame_jpg?video=${curVid}&frame=${fetchF}`),
      ]);
      frameData = data;
      bgImg = img;
      renderCanvas();
      updateSidebarInfo();
      if (targetFrame === fetchF) break;
    }
  } finally {
    fetchInFlight = false;
  }
}

function stepFrame(delta) {
  goToFrame(curFrame + delta);
}

function togglePlay() {
  playing = !playing;
  const btn = document.getElementById("playBtn");
  if (playing) {
    btn.textContent = "⏸ Pause (Space)";
    const stepLoop = async () => {
      if (!playing) return;
      if (curFrame >= maxFrames) { togglePlay(); return; }
      await goToFrame(curFrame + 1);
      const delay = parseInt(document.getElementById("speedSelect").value);
      playTimer = setTimeout(stepLoop, delay);
    };
    stepLoop();
  } else {
    btn.textContent = "▶ Play (Space)";
    if (playTimer) clearTimeout(playTimer);
  }
}

function jumpBookmark(dir) {
  if (!bookmarks.length) return;
  if (dir > 0) {
    const next = bookmarks.find(b => b > curFrame) || bookmarks[0];
    goToFrame(next);
  } else {
    const prev = [...bookmarks].reverse().find(b => b < curFrame) || bookmarks[bookmarks.length - 1];
    goToFrame(prev);
  }
}

function drawMinimapTopLeft() {
  const mx = 14, my = 14, mw = 236, mh = 174, pad = 12;
  ctx.save();
  ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
  ctx.fillRect(mx, my, mw, mh);
  ctx.strokeStyle = "#475569";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(mx, my, mw, mh);

  const cw = mw - 2 * pad;
  const ch = mh - 2 * pad;
  const c2u = (cx) => mx + pad + ((1505.0 - cx) / 1505.0) * cw;
  const c2v = (cy) => my + pad + (cy / 1105.0) * ch;

  ctx.fillStyle = "#1e3a8a";
  ctx.fillRect(mx + pad, my + pad, cw, ch);
  ctx.fillStyle = "rgba(148, 163, 184, 0.35)";
  const kx1 = c2u(1002.5), kx2 = c2u(502.5), ky1 = c2v(0), ky2 = c2v(580);
  ctx.fillRect(kx1, ky1, kx2 - kx1, ky2 - ky1);
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.strokeRect(mx + pad, my + pad, cw, ch);
  ctx.strokeRect(kx1, ky1, kx2 - kx1, ky2 - ky1);

  // Hoop at (752.5, 95) drawn as thin court-line ring (only 6 player dots in 2 colors appear)
  ctx.beginPath();
  ctx.arc(c2u(752.5), c2v(95.0), 3.5, 0, Math.PI * 2);
  ctx.strokeStyle = "#cbd5e1";
  ctx.lineWidth = 1;
  ctx.stroke();

  roster.forEach(id => {
    const r = frameData[id];
    if (!r) return;
    const team = id.split("#")[0];
    const col = TEAM_COLORS[team];
    const px = Math.max(mx + 4, Math.min(mx + mw - 4, c2u(r[4])));
    const py = Math.max(my + 4, Math.min(my + mh - 4, c2v(r[5])));
    ctx.beginPath();
    ctx.arc(px, py, id === selectedIdent ? 6.5 : 4.5, 0, Math.PI * 2);
    ctx.fillStyle = col;
    ctx.fill();
    ctx.lineWidth = id === selectedIdent ? 2 : 1;
    ctx.strokeStyle = id === selectedIdent ? "#ffffff" : "#000000";
    ctx.stroke();
    ctx.fillStyle = col;
    ctx.font = "bold 10px sans-serif";
    ctx.fillText(id.split("#")[1], px + 6, py + 3);
  });

  ctx.fillStyle = "#94a3b8";
  ctx.font = "bold 10px sans-serif";
  ctx.fillText("2D COURT MAP (Rổ ở trên - Cùng chiều Camera)", mx + 8, my + mh - 3);
  ctx.restore();
}

function getHandles(x1, y1, x2, y2) {
  const xm = 0.5 * (x1 + x2), ym = 0.5 * (y1 + y2);
  return [
    { name: "tl", x: x1, y: y1 },
    { name: "tm", x: xm, y: y1 },
    { name: "tr", x: x2, y: y1 },
    { name: "ml", x: x1, y: ym },
    { name: "mr", x: x2, y: ym },
    { name: "bl", x: x1, y: y2 },
    { name: "bm", x: xm, y: y2 },
    { name: "br", x: x2, y: y2 },
  ];
}

function renderCanvas() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (bgImg.complete && bgImg.naturalWidth > 0) {
    ctx.drawImage(bgImg, 0, 0, 1280, 720);
  }

  roster.forEach(id => {
    const r = frameData[id];
    if (!r) return;
    const [x1, y1, x2, y2, cx, cy, obs, edited] = r;
    const isSel = (id === selectedIdent);
    const team = id.split("#")[0];
    const col = TEAM_COLORS[team];

    ctx.save();
    ctx.strokeStyle = isSel ? "#ffffff" : col;
    ctx.lineWidth = isSel ? 2.5 : 1.8;
    if (!obs && !edited) ctx.setLineDash([4, 3]);
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.setLineDash([]);

    const lbl = `${id}${edited ? " ★" : (!obs ? " (interp)" : "")}`;
    ctx.font = "bold 12px sans-serif";
    const tw = ctx.measureText(lbl).width;
    ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw + 8, 18);
    ctx.fillStyle = col;
    ctx.fillText(lbl, x1 + 4, Math.max(13, y1 - 5));

    const uFoot = 0.5 * (x1 + x2);
    const vFoot = y2;
    ctx.beginPath();
    ctx.arc(uFoot, vFoot, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = col;
    ctx.fill();
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = "#000000";
    ctx.stroke();

    if (isSel) {
      getHandles(x1, y1, x2, y2).forEach(h => {
        ctx.fillStyle = h.name === "bm" ? "#22c55e" : "#ffffff";
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1.2;
        ctx.fillRect(h.x - 4, h.y - 4, 8, 8);
        ctx.strokeRect(h.x - 4, h.y - 4, 8, 8);
      });
    }
    ctx.restore();

    const tagEl = document.getElementById(`tag_${id}`);
    if (tagEl) tagEl.textContent = edited ? "★" : (!obs ? "○" : "●");
  });

  drawMinimapTopLeft();
}

function updateSidebarInfo() {
  const r = frameData[selectedIdent];
  if (!r) return;
  const [x1, y1, x2, y2, cx, cy, obs, edited] = r;
  const uFoot = (0.5 * (x1 + x2)).toFixed(1);
  const vFoot = y2.toFixed(1);
  document.getElementById("boxInfo").innerHTML = `
    <div>Cầu thủ : <b style="color:#38bdf8">${selectedIdent}</b> (${edited ? "Đã chỉnh ★" : (obs ? "YOLO26m Obs" : "Nội suy")})</div>
    <div>BBox    : [${x1.toFixed(1)}, ${y1.toFixed(1)}, ${x2.toFixed(1)}, ${y2.toFixed(1)}]</div>
    <div>Đáy giữa: <b>(${uFoot}, ${vFoot}) px</b></div>
    <div>Tọa độ sân: <b style="color:#34d399">(${cx.toFixed(1)}, ${cy.toFixed(1)}) cm</b></div>
  `;
}

function getMousePos(evt) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (evt.clientX - rect.left) * scaleX,
    y: (evt.clientY - rect.top) * scaleY
  };
}

canvas.addEventListener("mousedown", (evt) => {
  const pos = getMousePos(evt);
  if (drawNewBoxMode) {
    dragState = { mode: "draw", startX: pos.x, startY: pos.y, origBox: [pos.x, pos.y, pos.x + 20, pos.y + 50] };
    return;
  }

  const selR = frameData[selectedIdent];
  if (selR) {
    const handles = getHandles(selR[0], selR[1], selR[2], selR[3]);
    for (const h of handles) {
      if (Math.hypot(pos.x - h.x, pos.y - h.y) <= 8) {
        dragState = { mode: "resize", handle: h.name, startX: pos.x, startY: pos.y, origBox: [...selR.slice(0, 4)] };
        return;
      }
    }
  }

  const checkOrder = [selectedIdent, ...roster.filter(i => i !== selectedIdent)];
  for (const id of checkOrder) {
    const r = frameData[id];
    if (!r) continue;
    if (pos.x >= r[0] && pos.x <= r[2] && pos.y >= r[1] && pos.y <= r[3]) {
      if (id !== selectedIdent) selectPlayer(id);
      dragState = { mode: "move", startX: pos.x, startY: pos.y, origBox: [...r.slice(0, 4)] };
      return;
    }
  }
});

canvas.addEventListener("mousemove", (evt) => {
  if (!dragState) return;
  const pos = getMousePos(evt);
  const dx = pos.x - dragState.startX;
  const dy = pos.y - dragState.startY;
  let [x1, y1, x2, y2] = dragState.origBox;

  if (dragState.mode === "move") {
    x1 += dx; x2 += dx; y1 += dy; y2 += dy;
  } else if (dragState.mode === "draw") {
    x1 = Math.min(dragState.startX, pos.x);
    y1 = Math.min(dragState.startY, pos.y);
    x2 = Math.max(dragState.startX + 8, pos.x);
    y2 = Math.max(dragState.startY + 16, pos.y);
  } else if (dragState.mode === "resize") {
    const h = dragState.handle;
    if (h.includes("l")) x1 += dx;
    if (h.includes("r")) x2 += dx;
    if (h.includes("t")) y1 += dy;
    if (h.includes("b")) y2 += dy;
  }

  if (x2 < x1 + 6) x2 = x1 + 6;
  if (y2 < y1 + 12) y2 = y1 + 12;
  const r = frameData[selectedIdent];
  const [cx, cy] = clientImgToCourt(0.5 * (x1 + x2), y2);
  r[0] = x1; r[1] = y1; r[2] = x2; r[3] = y2; r[4] = cx; r[5] = cy; r[7] = true;
  renderCanvas();
  updateSidebarInfo();
});

window.addEventListener("mouseup", async () => {
  if (!dragState) return;
  const mode = dragState.mode;
  dragState = null;
  if (mode === "draw") toggleDrawMode(false);
  const r = frameData[selectedIdent];
  const res = await fetch("/api/update_box", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video: curVid,
      frame: curFrame,
      ident: selectedIdent,
      x1: r[0], y1: r[1], x2: r[2], y2: r[3]
    })
  });
  const updated = await res.json();
  frameData[selectedIdent] = updated;
  renderCanvas();
  updateSidebarInfo();
  document.getElementById("saveStatus").textContent = `Đã sửa ${selectedIdent} @ f=${curFrame} (Nhấn Ctrl+S để lưu)`;
});

function toggleDrawMode(forceVal) {
  drawNewBoxMode = (forceVal !== undefined) ? forceVal : !drawNewBoxMode;
  const btn = document.getElementById("drawModeBtn");
  btn.textContent = `✏️ Chế độ Vẽ Lại Box (W): ${drawNewBoxMode ? "ON" : "OFF"}`;
  btn.className = drawNewBoxMode ? "primary" : "";
}

async function copyPrevFrame() {
  if (curFrame <= 1) return;
  const prevRes = await fetch(`/api/frame_data?video=${curVid}&frame=${curFrame - 1}`);
  const prevData = await prevRes.json();
  const pb = prevData[selectedIdent];
  if (!pb) return;
  const res = await fetch("/api/update_box", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video: curVid, frame: curFrame, ident: selectedIdent,
      x1: pb[0], y1: pb[1], x2: pb[2], y2: pb[3]
    })
  });
  frameData[selectedIdent] = await res.json();
  await goToFrame(Math.min(maxFrames, curFrame));
}

function setRangeStart() { document.getElementById("fStart").value = curFrame; }
function setRangeEnd() { document.getElementById("fEnd").value = curFrame; }

async function interpolateRange() {
  const f1 = parseInt(document.getElementById("fStart").value);
  const f2 = parseInt(document.getElementById("fEnd").value);
  await fetch("/api/interpolate_range", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video: curVid, ident: selectedIdent, f1, f2 })
  });
  await goToFrame(curFrame);
  document.getElementById("saveStatus").textContent = `Đã nội suy ${selectedIdent} [${f1}..${f2}]`;
}

async function interpolateFromAnchor() {
  const f1 = parseInt(document.getElementById("fStart").value);
  const f2 = parseInt(document.getElementById("fEnd").value);
  const anchor = curFrame;
  await fetch("/api/interpolate_from_anchor", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video: curVid, ident: selectedIdent, f1, f2, anchor })
  });
  await goToFrame(curFrame);
  document.getElementById("saveStatus").textContent = `Đã nội suy anchor ${selectedIdent} @ f=${anchor} [${f1}..${f2}]`;
}

async function swapRange() {
  const f1 = parseInt(document.getElementById("fStart").value);
  const f2 = parseInt(document.getElementById("fEnd").value);
  const id1 = document.getElementById("swapA").value;
  const id2 = document.getElementById("swapB").value;
  if (id1 === id2) return;
  await fetch("/api/swap_range", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video: curVid, id1, id2, f1, f2 })
  });
  await goToFrame(curFrame);
  document.getElementById("saveStatus").textContent = `Đã đổi ${id1} ⇄ ${id2} [${f1}..${f2}]`;
}

async function saveGT() {
  document.getElementById("saveStatus").textContent = "Đang lưu...";
  const res = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video: curVid })
  });
  const info = await res.json();
  document.getElementById("saveStatus").textContent = `Đã lưu vào output_ground_truth/${curVid}.txt (${info.edited_boxes} box đã chỉnh)`;
}

async function downloadGT() {
  await saveGT();
  window.location.href = `/api/download_txt?video=${curVid}`;
}

window.addEventListener("keydown", (evt) => {
  if (evt.target.tagName === "INPUT" || evt.target.tagName === "SELECT") return;
  if (evt.ctrlKey && (evt.key === "s" || evt.key === "S")) {
    evt.preventDefault();
    saveGT();
    return;
  }
  if (evt.key === " ") { evt.preventDefault(); togglePlay(); }
  else if (evt.key === "ArrowLeft" || evt.key === "a" || evt.key === "A") stepFrame(evt.shiftKey ? -10 : -1);
  else if (evt.key === "ArrowRight" || evt.key === "d" || evt.key === "D") stepFrame(evt.shiftKey ? 10 : 1);
  else if (evt.key === "q" || evt.key === "Q") stepFrame(-10);
  else if (evt.key === "e" || evt.key === "E") stepFrame(10);
  else if (evt.key === "w" || evt.key === "W") toggleDrawMode();
  else if (evt.key === "c" || evt.key === "C") copyPrevFrame();
  else if (evt.key === "i" || evt.key === "I") setRangeStart();
  else if (evt.key === "o" || evt.key === "O") setRangeEnd();
  else if (evt.key === "k" || evt.key === "K") interpolateRange();
  else if (evt.key === "j" || evt.key === "J") interpolateFromAnchor();
  else if (evt.key === "n" || evt.key === "N") jumpBookmark(1);
  else if (evt.key === "p" || evt.key === "P") jumpBookmark(-1);
  else if (evt.key >= "1" && evt.key <= "6") {
    const idx = parseInt(evt.key) - 1;
    if (roster[idx]) selectPlayer(roster[idx]);
  }
});

function openGdriveModal() {
  document.getElementById("gdriveTargetVid").value = curVid;
  document.getElementById("gdriveModal").style.display = "flex";
  document.getElementById("gdriveUrlInput").focus();
}

function closeGdriveModal() {
  document.getElementById("gdriveModal").style.display = "none";
  document.getElementById("gdriveProgress").style.display = "none";
  document.getElementById("gdriveSubmitBtn").disabled = false;
}

async function submitGdriveVideo() {
  const url = document.getElementById("gdriveUrlInput").value.trim();
  const targetVid = document.getElementById("gdriveTargetVid").value;
  if (!url) {
    alert("Vui lòng nhập link Google Drive hoặc File ID!");
    return;
  }
  const progEl = document.getElementById("gdriveProgress");
  const submitBtn = document.getElementById("gdriveSubmitBtn");
  progEl.style.display = "block";
  progEl.textContent = `⏳ Đang tải video cho ${targetVid} từ Google Drive và thay thế file gốc... Quá trình có thể mất 30-60 giây tùy dung lượng.`;
  submitBtn.disabled = true;

  try {
    const res = await fetch("/api/replace_video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video: targetVid, url: url })
    });
    const result = await res.json();
    if (result.ok) {
      alert(`✅ ${result.message}`);
      closeGdriveModal();
      document.getElementById("gdriveUrlInput").value = "";
      if (curVid === targetVid) {
        await goToFrame(curFrame);
      }
    } else {
      alert(`❌ Lỗi tải video: ${result.error || "Không thể tải video"}`);
      progEl.style.display = "none";
      submitBtn.disabled = false;
    }
  } catch (err) {
    alert(`❌ Lỗi kết nối: ${err.message}`);
    progEl.style.display = "none";
    submitBtn.disabled = false;
  }
}

initVideoMeta();
</script>

<!-- Google Drive Video Loader Modal -->
<div id="gdriveModal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; align-items:center; justify-content:center;">
  <div style="background:#1e293b; border:1px solid #475569; border-radius:10px; width:480px; padding:20px; box-shadow:0 10px 25px rgba(0,0,0,0.6);">
    <h3 style="margin-top:0; color:#38bdf8; display:flex; justify-content:space-between; align-items:center;">
      <span>📥 Nạp Video từ Google Drive</span>
      <span style="cursor:pointer; color:#94a3b8; font-size:18px;" onclick="closeGdriveModal()">✖</span>
    </h3>
    <p style="font-size:12.5px; color:#cbd5e1; line-height:1.5;">
      Dán link chia sẻ Google Drive (hoặc File ID). Video tải về sẽ tự động ghi đè vào thư mục <code>videos_source/</code> để công cụ đọc frame trực tiếp.
    </p>
    <div style="margin:12px 0;">
      <label style="font-size:12px; color:#94a3b8; font-weight:600;">Video đích để thay thế:</label>
      <select id="gdriveTargetVid" style="width:100%; margin-top:4px;">
        <option value="IMG_0114">IMG_0114 (videos_source/IMG_0114.MP4)</option>
        <option value="IMG_0115">IMG_0115 (videos_source/IMG_0115.MP4)</option>
      </select>
    </div>
    <div style="margin:12px 0;">
      <label style="font-size:12px; color:#94a3b8; font-weight:600;">Link Google Drive / File ID / Direct URL:</label>
      <input id="gdriveUrlInput" type="text" placeholder="https://drive.google.com/file/d/.../view?usp=sharing" style="width:100%; margin-top:4px; box-sizing:border-box;"/>
    </div>
    <div id="gdriveProgress" style="display:none; font-size:12px; color:#38bdf8; margin:10px 0; font-weight:600;">
      ⏳ Đang tải video từ Google Drive... vui lòng đợi trong giây lát...
    </div>
    <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
      <button onclick="closeGdriveModal()">Hủy</button>
      <button id="gdriveSubmitBtn" class="primary" onclick="submitGdriveVideo()">Tải & Thay Thế Video</button>
    </div>
  </div>
</div>
</body>
</html>
"""


class GTHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/meta":
            vid = qs.get("video", ["IMG_0114"])[0]
            d = STORE.data[vid]
            self._send_json({
                "max_frames": d["max_frames"],
                "roster": d["roster"],
                "bookmarks": STORE.flagged_frames[vid],
            })
        elif parsed.path == "/api/frame_data":
            vid = qs.get("video", ["IMG_0114"])[0]
            f = int(qs.get("frame", ["1"])[0])
            self._send_json(STORE.data[vid]["frames"][f])
        elif parsed.path == "/api/frame_jpg":
            vid = qs.get("video", ["IMG_0114"])[0]
            f = int(qs.get("frame", ["1"])[0])
            jpg = STORE.get_jpeg_frame(vid, f)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
        elif parsed.path == "/api/download_txt":
            vid = qs.get("video", ["IMG_0114"])[0]
            txt_p = GT_DIR / f"{vid}.txt"
            if not txt_p.exists():
                STORE.save_video_gt(vid)
            data = txt_p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{vid}.txt"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/api/update_box":
            rec = STORE.update_box(
                payload["video"],
                int(payload["frame"]),
                payload["ident"],
                float(payload["x1"]),
                float(payload["y1"]),
                float(payload["x2"]),
                float(payload["y2"]),
            )
            self._send_json(rec)
        elif self.path == "/api/interpolate_range":
            STORE.interpolate_range(payload["video"], payload["ident"], int(payload["f1"]), int(payload["f2"]))
            self._send_json({"ok": True})
        elif self.path == "/api/interpolate_from_anchor":
            STORE.interpolate_from_anchor(payload["video"], payload["ident"], int(payload["f1"]), int(payload["f2"]), int(payload["anchor"]))
            self._send_json({"ok": True})
        elif self.path == "/api/swap_range":
            STORE.swap_players_range(payload["video"], payload["id1"], payload["id2"], int(payload["f1"]), int(payload["f2"]))
            self._send_json({"ok": True})
        elif self.path == "/api/save":
            info = STORE.save_video_gt(payload["video"])
            self._send_json(info)
        elif self.path == "/api/replace_video":
            try:
                res = STORE.replace_video_source(payload["video"], payload["url"])
                self._send_json(res)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})
        else:
            self.send_error(404)


def find_free_port(start_port: int = 8899) -> int:
    for p in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start_port


def main():
    global STORE
    STORE = VideoStore()
    port = find_free_port(8899)
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    server = ThreadingHTTPServer(("0.0.0.0", port), GTHandler)
    url = f"http://127.0.0.1:{port}"
    print("============================================================================", flush=True)
    print(f"  3x3 Basketball Ground-Truth Box Editor running at: {url}", flush=True)
    print(f"  Output files are saved in: {GT_DIR}", flush=True)
    print("============================================================================", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
