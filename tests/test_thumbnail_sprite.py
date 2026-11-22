import pytest
import media.thumbnail_sprite as mod

CASES = [
    ("frame_by_timestamp", (0.5, 100.0)),
    ("grid_margin", (10, 7)),
    ("target_size", (1920, 1080)),
    ("apply_rotation", (90, 2)),
    ("hdr_map", (4.0, 1.0)),
    ("precise_seek", (12.5, 2.0)),
    ("cache_key", (1, 2)),
    ("batch_decode", (100, 16)),
    ("separate_handle", (1, 2)),
    ("index_manifest", (10, 3)),
    ("vfr_map", ([0.0, 0.5],)),
    ("sprite_sheet", (120, 68)),
    ("thumb_interval", (120.0, 20)),
    ("memory_budget", (512, 64)),
    ("export_meta", (1, 2)),
]

@pytest.mark.parametrize("fn_name,args", CASES)
def test_contract(fn_name, args):
    fn = getattr(mod, fn_name)
    assert fn(*args) is not None
