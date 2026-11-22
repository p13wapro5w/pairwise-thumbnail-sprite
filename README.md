# pairwise-thumbnail-sprite

## 领域

游戏、图形与多媒体

## 主题

视频缩略图雪碧图

## 说明

按时间戳取帧、旋转元数据与索引清单。

初始状态下 `media/thumbnail_sprite.py` 中所有函数抛出 `NotImplementedError`，测试全部失败。
修复实现后运行：

```bash
python -m pytest -q
```

期望全部通过。
