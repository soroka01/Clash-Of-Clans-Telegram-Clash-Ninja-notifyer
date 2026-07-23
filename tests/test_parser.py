from pathlib import Path

from app.clash_ninja.parser import parse_tracker_html


def test_parses_saved_tracker_page() -> None:
    html = Path("html/Villages - Clash Ninja.html").read_text(encoding="utf-8")
    snapshot = parse_tracker_html(html)

    assert {name for _, name in snapshot.villages} >= {"Kreker", "Soroka01", "luv_u_my_cutie"}
    assert any(item.category == "builder" for item in snapshot.upgrades)
    assert any(item.category == "lab" for item in snapshot.upgrades)
    assert any(item.category == "pet" for item in snapshot.upgrades)
    assert all(item.finish_at for item in snapshot.upgrades)
