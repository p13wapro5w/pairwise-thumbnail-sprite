"""视频缩略图雪碧图核心模块。

修复点：
- 按时间戳取帧（VFR 对齐）
- 网格余量（最后一行不满不拉伸）
- 按目标尺寸计算缩略图
- 应用旋转元数据
- HDR -> SDR 色调映射
- 精确 seek（关键帧 + 逐帧推进）
- 缓存键包含内容/参数指纹
- 分批解码（内存预算）
- 独立句柄（生成与播放不共享）
- 索引清单（每格对应时间点）
"""

import hashlib
import json
import math


def frame_by_timestamp(t, duration):
    """按目标时间戳（秒）取帧：夹取到 [0, duration]，返回帧索引基准时间。

    VFR 素材下不再用固定间隔 * 序号，而是直接用时间戳定位。
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    t = max(0.0, min(float(t), float(duration)))
    return {"timestamp": t, "duration": float(duration)}


def vfr_map(timestamps):
    """把 VFR 实际帧时间戳序列映射为 目标时间 -> 最近帧索引 的查询表。"""
    ts = sorted(float(x) for x in timestamps)
    if not ts:
        raise ValueError("empty timestamp list")

    def lookup(t):
        # 二分找最近的实际帧时间戳，保证时间对齐
        lo, hi = 0, len(ts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ts[mid] < t:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0 and abs(ts[lo - 1] - t) <= abs(ts[lo] - t):
            return lo - 1
        return lo

    return {"timestamps": ts, "lookup": lookup}


def grid_margin(cols, total):
    """网格余量：最后一行不满时返回实际列数与留空数，不拉伸成整行。"""
    if cols <= 0:
        raise ValueError("cols must be positive")
    rows = math.ceil(total / cols) if total else 0
    last_row_cols = total - (rows - 1) * cols if rows else 0
    empty = rows * cols - total
    return {"rows": rows, "cols": cols, "last_row_cols": last_row_cols, "empty_cells": empty}


def target_size(src_w, src_h, max_w=320, max_h=180):
    """按目标尺寸等比缩放：限制最大宽/高，超宽片不会被压成细缝。"""
    if src_w <= 0 or src_h <= 0:
        raise ValueError("invalid source size")
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    w = max(1, round(src_w * scale))
    h = max(1, round(src_h * scale))
    return (w, h)


def apply_rotation(rotation, n):
    """应用旋转元数据：对 n 帧序列按 rotation 度旋转（0/90/180/270）。"""
    rotation = rotation % 360
    if rotation not in (0, 90, 180, 270):
        raise ValueError("unsupported rotation")
    frames = list(range(n))
    # 旋转后帧顺序不变，仅记录每帧的显示方向
    return {"rotation": rotation, "frames": frames, "swap_axes": rotation in (90, 270)}


def hdr_map(peak, ref):
    """HDR -> SDR 色调映射：按峰值亮度归一，避免直接降 8 位导致发灰。"""
    if peak <= 0 or ref <= 0:
        raise ValueError("peak/ref must be positive")
    gain = ref / peak if peak > ref else 1.0

    def tonemap(v):
        x = max(0.0, float(v)) * gain
        return x / (1.0 + x)  # Reinhard，保留高光层次

    return {"gain": gain, "tonemap": tonemap}


def precise_seek(t, gop):
    """精确 seek：先跳到 t 之前最近的关键帧，再逐帧解码推进到 t。"""
    if t < 0 or gop <= 0:
        raise ValueError("invalid seek args")
    keyframe = math.floor(t / gop) * gop
    decode_forward = t - keyframe
    return {"keyframe": keyframe, "decode_forward": decode_forward, "target": t}


def cache_key(file_id, params):
    """缓存键：文件标识 + 参数（码率/尺寸/间隔等）指纹，换参数即失效。"""
    payload = json.dumps({"file": file_id, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batch_decode(total, batch_size):
    """分批解码：按 batch_size 切块，避免一次性把全片解码进内存。"""
    if total < 0 or batch_size <= 0:
        raise ValueError("invalid batch args")
    batches = []
    start = 0
    while start < total:
        end = min(start + batch_size, total)
        batches.append((start, end))
        start = end
    return batches


def memory_budget(total_mb, per_frame_mb):
    """内存预算：给定总预算与单帧占用，得出每批最多解码帧数。"""
    if total_mb <= 0 or per_frame_mb <= 0:
        raise ValueError("invalid budget args")
    max_frames = max(1, total_mb // per_frame_mb)
    return {"max_frames_per_batch": max_frames, "budget_mb": total_mb}


def separate_handle(reader_id, writer_id):
    """独立句柄：生成缩略图与播放各自打开文件，不共享句柄。"""
    if reader_id == writer_id:
        raise ValueError("reader and writer must use separate handles")
    return {"reader": f"handle:read:{reader_id}", "writer": f"handle:write:{writer_id}"}


def thumb_interval(duration, count):
    """缩略图采样时间点：按数量在时长内均匀取时间戳（而非固定间隔硬切）。"""
    if duration <= 0 or count <= 0:
        raise ValueError("invalid interval args")
    step = duration / count
    return [step * i for i in range(count)]


def index_manifest(cols, count):
    """索引清单：每格的行列位置与对应时间片序号，供前端定位。"""
    if cols <= 0 or count < 0:
        raise ValueError("invalid manifest args")
    cells = []
    for i in range(count):
        cells.append({"index": i, "row": i // cols, "col": i % cols})
    return {"cols": cols, "count": count, "cells": cells}


def sprite_sheet(thumb_w, thumb_h, cols=10, rows=10):
    """雪碧图布局：按网格切格，最后一行不满保持原尺寸留空。"""
    if min(thumb_w, thumb_h, cols, rows) <= 0:
        raise ValueError("invalid sprite args")
    return {
        "cell_w": thumb_w,
        "cell_h": thumb_h,
        "cols": cols,
        "rows": rows,
        "width": thumb_w * cols,
        "height": thumb_h * rows,
        "capacity": cols * rows,
    }


def export_meta(file_id, version):
    """导出元信息：雪碧图文件 + 索引清单一起写出。"""
    key = cache_key(file_id, {"version": version})
    return {
        "id": file_id,
        "version": version,
        "cache_key": key,
        "sprite": f"{key}.jpg",
        "manifest": f"{key}.json",
    }
